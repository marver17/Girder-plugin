import datetime
import json
import io
from pathlib import Path

import nibabel as nib
import numpy as np

from girder import events
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource
from girder.constants import AccessType, TokenScope
from girder.exceptions import RestException
from girder.plugin import GirderPlugin, registerPluginStaticContent
from girder.models.item import Item
from girder.models.file import File
from girder.utility import search


class NiftiViewerPlugin(GirderPlugin):
    DISPLAY_NAME = 'NIfTI Viewer'
    CLIENT_SOURCE_PATH = 'web_client'

    def load(self, info):
        # Expose the 'nifti' field on items
        Item().exposeFields(level=AccessType.READ, fields={'nifti'})
        
        # Bind event handler for automatic parsing on upload
        events.bind('data.process', 'nifti_viewer', _uploadHandler)

        # Add NIfTI search mode
        search.addSearchMode('nifti', niftiSubstringSearchHandler)

        # Register REST endpoints
        niftiItem = NiftiItem()
        info['apiRoot'].item.route(
            'POST', (':id', 'parseNifti'), niftiItem.makeNiftiItem)

        # Register static content (JavaScript and CSS)
        registerPluginStaticContent(
            plugin='nifti_viewer',
            css=['/style.css'],
            js=['/girder-plugin-nifti-viewer.umd.cjs'],
            staticDir=Path(__file__).parent / 'web_client' / 'dist',
            tree=info['serverRoot'],
        )


class NiftiItem(Resource):

    @access.user(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Parse NIfTI files and extract metadata from NIfTI header and optional JSON sidecar')
        .modelParam('id', 'The item ID',
                    model='item', level=AccessType.WRITE, paramType='path')
        .errorResponse('ID was invalid.')
        .errorResponse('Write permission denied on the item.', 403)
    )
    def makeNiftiItem(self, item):
        """
        Convert an existing item into a "NIfTI item", which contains
        extracted metadata from NIfTI header and optional JSON sidecar files.
        """
        niftiFile = None
        jsonFile = None
        
        # Find NIfTI and JSON files in the item
        for file in Item().childFiles(item):
            name = file['name'].lower()
            if name.endswith('.nii') or name.endswith('.nii.gz'):
                niftiFile = file
            elif name.endswith('.json'):
                jsonFile = file
        
        if not niftiFile:
            # No NIfTI file found, just return the item unchanged
            return item
        
        # Parse NIfTI header metadata
        try:
            niftiMeta = _parseNiftiFile(niftiFile)
        except Exception as e:
            raise RestException(f'Failed to parse NIfTI file: {str(e)}')
        
        # Parse JSON metadata if present (optional)
        jsonMeta = {}
        if jsonFile:
            try:
                jsonMeta = _parseJsonFile(jsonFile)
            except Exception as e:
                # JSON parsing is optional, log warning but continue
                print(f'Warning: Failed to parse JSON file: {str(e)}')
        
        # Combine metadata
        combinedMeta = {**niftiMeta}
        if jsonMeta:
            combinedMeta['json_metadata'] = jsonMeta
        
        # Build files array (JavaScript expects an array, not an object)
        files = [_extractFileData(niftiFile)]
        if jsonFile:
            files.append(_extractFileData(jsonFile))
        
        # Store in the item
        item['nifti'] = {
            'meta': combinedMeta,
            'files': files
        }
        
        # Save the item
        return Item().save(item)


def _parseNiftiFile(file):
    """
    Extract metadata from NIfTI file header using nibabel.
    Supports both compressed (.nii.gz) and uncompressed (.nii) files.
    
    :param file: Girder file document
    :returns: Dictionary with NIfTI metadata
    """
    import tempfile
    import shutil
    import os
    
    # Determine the correct file extension based on the original file name
    filename = file['name'].lower()
    if filename.endswith('.nii.gz'):
        suffix = '.nii.gz'
    elif filename.endswith('.nii'):
        suffix = '.nii'
    else:
        # Fallback - try both extensions
        suffix = '.nii.gz'
    
    # Save to temporary file (nibabel needs a file path)
    # Use streaming to avoid loading entire file in memory
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name
        with File().open(file) as f:
            # Stream the file in chunks to avoid memory issues
            shutil.copyfileobj(f, tmp, length=1024*1024)  # 1MB chunks
        # Ensure all data is written to disk before reading
        tmp.flush()
    
    try:
        # Load with nibabel
        img = nib.load(tmp_path)
        header = img.header
        
        # Extract key metadata
        # Use field names that match frontend expectations
        dims = list(header.get_data_shape())
        pixdim = [float(x) for x in header.get_zooms()]

        meta = {
            # Frontend-compatible field names
            'dimensions': dims,  # Frontend expects 'dimensions'
            'pixelSpacing': pixdim,  # Frontend expects 'pixelSpacing'
            'dataType': str(header.get_data_dtype()),  # Frontend expects 'dataType'
            'units': _get_space_units(header),  # Frontend expects just the string

            # Keep legacy field names for backward compatibility
            'dims': dims,
            'pixdim': pixdim,
            'datatype': str(header.get_data_dtype()),

            # Additional metadata
            'qform_code': int(header['qform_code']),
            'sform_code': int(header['sform_code']),
            'time_units': _get_time_units(header),
            'file_type': 'NIfTI-1' if header['sizeof_hdr'] == 348 else 'NIfTI-2',
        }
        
        # Add orientation if available
        try:
            orientation = nib.aff2axcodes(img.affine)
            meta['orientation'] = ''.join(orientation)
        except Exception:
            meta['orientation'] = 'Unknown'

        # Add affine matrix
        try:
            meta['affine'] = img.affine.tolist()
        except Exception:
            meta['affine'] = None

        # Add voxel volume (frontend expects 'voxelSize')
        try:
            voxel_volume = np.prod(header.get_zooms()[:3])
            meta['voxelSize'] = float(voxel_volume)  # Frontend field name
            meta['voxel_volume'] = float(voxel_volume)  # Legacy field name
        except Exception:
            meta['voxelSize'] = None
            meta['voxel_volume'] = None

        # Add image size in bytes (frontend expects 'imageSize')
        try:
            # Calculate total image size (dimensions × bytes per voxel)
            bytes_per_voxel = header.get_data_dtype().itemsize
            total_voxels = np.prod(dims)
            image_size_bytes = total_voxels * bytes_per_voxel
            # Frontend expects [width, height, depth] format
            meta['imageSize'] = dims  # Same as dimensions for 3D images
        except Exception:
            meta['imageSize'] = dims

        return meta
    finally:
        # Clean up temporary file
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _get_space_units(header):
    """Get spatial units from NIfTI header."""
    units_dict = {
        0: 'unknown',
        1: 'meter',
        2: 'mm',
        3: 'micron'
    }
    try:
        unit_code = header.get_xyzt_units()[0]
        return units_dict.get(unit_code, 'unknown')
    except Exception:
        return 'unknown'


def _get_time_units(header):
    """Get temporal units from NIfTI header."""
    units_dict = {
        0: 'unknown',
        8: 'sec',
        16: 'msec',
        24: 'usec',
        32: 'Hz',
        40: 'ppm',
        48: 'rads'
    }
    try:
        unit_code = header.get_xyzt_units()[1]
        return units_dict.get(unit_code, 'unknown')
    except Exception:
        return 'unknown'


def _parseJsonFile(file):
    """
    Parse JSON sidecar file (e.g., BIDS-style metadata).
    
    :param file: Girder file document
    :returns: Dictionary with JSON content
    """
    with File().open(file) as f:
        content = f.read()
        if isinstance(content, bytes):
            content = content.decode('utf-8')
        return json.loads(content)


def _extractFileData(file):
    """
    Extract basic file information.
    
    :param file: Girder file document
    :returns: Dictionary with file metadata
    """
    return {
        'id': str(file['_id']),
        'name': file['name'],
        'size': file['size'],
        'created': file.get('created', datetime.datetime.utcnow()).isoformat()
    }


def _uploadHandler(event):
    """
    Event handler to automatically parse NIfTI files on upload.
    """
    import logging
    logger = logging.getLogger('girder.plugins.nifti_viewer')
    
    logger.info('=== NIfTI Upload Handler Called ===')
    logger.info(f'Event info keys: {list(event.info.keys())}')
    
    file = event.info.get('file')
    if not file:
        logger.warning('No file in event.info')
        return
    
    name = file.get('name', '').lower()
    logger.info(f'File name: {name}')
    
    # Check if it's a NIfTI file
    if name.endswith('.nii') or name.endswith('.nii.gz'):
        logger.info(f'Processing NIfTI file: {name}')
        try:
            # Parse the NIfTI file
            logger.info('Parsing NIfTI file...')
            fileMetadata = _parseNiftiFile(file)
            if fileMetadata is None:
                logger.warning('Failed to parse NIfTI file')
                return
            
            logger.info(f'Parsed metadata: {list(fileMetadata.keys())}')
            
            item = Item().load(file['itemId'], force=True)
            if not item:
                logger.warning('Failed to load item')
                return
            
            logger.info(f'Loaded item: {item["_id"]}')
            
            # Check for JSON sidecar
            jsonMetadata = None
            itemFiles = list(File().find({'itemId': item['_id']}))
            logger.info(f'Found {len(itemFiles)} files in item')
            for itemFile in itemFiles:
                if itemFile['name'].endswith('.json'):
                    logger.info(f'Found JSON sidecar: {itemFile["name"]}')
                    jsonMetadata = _parseJsonFile(itemFile)
                    break
            
            # Update or create nifti metadata in item
            if 'nifti' in item:
                logger.info('Updating existing nifti metadata')
                # Update existing metadata
                item['nifti']['meta'].update(fileMetadata)
                if jsonMetadata:
                    item['nifti']['meta'].update(jsonMetadata)
            else:
                logger.info('Creating new nifti metadata')
                # Create new metadata
                item['nifti'] = {
                    'meta': fileMetadata,
                    'files': []
                }
                if jsonMetadata:
                    item['nifti']['meta'].update(jsonMetadata)
            
            # Add file info
            fileInfo = _extractFileData(file)
            item['nifti']['files'].append(fileInfo)
            
            logger.info('Saving item with nifti metadata')
            Item().save(item)
            logger.info('=== NIfTI Upload Handler Completed Successfully ===')
        except Exception as e:
            logger.error(f'Error auto-parsing NIfTI file: {str(e)}', exc_info=True)
    else:
        logger.info(f'Not a NIfTI file, skipping: {name}')


def _buildSearchConditions(query):
    """
    Costruisce condizioni di ricerca MongoDB per tutti i campi metadati NIfTI.

    Cerca in:
    - Campi stringa header NIfTI (orientation, datatype, units, ecc.)
    - Campi metadati BIDS JSON (ProtocolName, Manufacturer, ecc.)
    - Nomi file
    - Campi array numerici quando la query è un numero

    :param query: Stringa di ricerca dall'utente
    :returns: Lista di condizioni query MongoDB
    """
    conditions = []

    # Campi stringa header NIfTI
    string_fields = [
        'nifti.meta.orientation',
        'nifti.meta.dataType',
        'nifti.meta.datatype',  # Campo legacy
        'nifti.meta.units',
        'nifti.meta.time_units',
        'nifti.meta.file_type',
    ]

    for field in string_fields:
        conditions.append({field: {'$regex': query, '$options': 'i'}})

    # Gestione query numeriche per campi array (dimensioni, spacing)
    try:
        numeric_query = float(query)
        # Cerca negli array dimensioni/spacing
        conditions.append({'nifti.meta.dimensions': numeric_query})
        conditions.append({'nifti.meta.dims': numeric_query})
        conditions.append({'nifti.meta.pixelSpacing': numeric_query})
        conditions.append({'nifti.meta.pixdim': numeric_query})
    except ValueError:
        # Non è un numero, salta ricerca array numerici
        pass

    # Campi metadati BIDS JSON (alto valore per utenti)
    bids_fields = [
        # Protocollo/Sequenza (più cercati)
        'nifti.meta.json_metadata.ProtocolName',
        'nifti.meta.json_metadata.SeriesDescription',
        'nifti.meta.json_metadata.SequenceName',
        'nifti.meta.json_metadata.PulseSequenceType',
        'nifti.meta.json_metadata.ScanningSequence',
        'nifti.meta.json_metadata.SequenceVariant',

        # Hardware scanner
        'nifti.meta.json_metadata.Manufacturer',
        'nifti.meta.json_metadata.ManufacturersModelName',
        'nifti.meta.json_metadata.DeviceSerialNumber',
        'nifti.meta.json_metadata.StationName',
        'nifti.meta.json_metadata.SoftwareVersions',

        # Istituzione
        'nifti.meta.json_metadata.InstitutionName',
        'nifti.meta.json_metadata.InstitutionAddress',
        'nifti.meta.json_metadata.InstitutionalDepartmentName',

        # Acquisizione
        'nifti.meta.json_metadata.MagneticFieldStrength',
        'nifti.meta.json_metadata.ReceiveCoilName',
        'nifti.meta.json_metadata.TransmitCoilName',
        'nifti.meta.json_metadata.ImageType',

        # Processing
        'nifti.meta.json_metadata.ConversionSoftware',
        'nifti.meta.json_metadata.ConversionSoftwareVersion',
    ]

    for field in bids_fields:
        conditions.append({field: {'$regex': query, '$options': 'i'}})

    # Nomi file (files è un array di oggetti con campo 'name')
    conditions.append({'nifti.files.name': {'$regex': query, '$options': 'i'}})

    return conditions


def niftiSubstringSearchHandler(query, types, user=None, level=None, limit=0, offset=0):
    """
    Search handler per item NIfTI.

    Esegue ricerca case-insensitive substring completa su:
    - Tutti i campi header NIfTI (orientation, datatype, dimensions, spacing, ecc.)
    - Tutti i campi metadati BIDS JSON (ProtocolName, Manufacturer, ecc.)
    - Nomi file

    :param query: Stringa di ricerca (substring case-insensitive)
    :param types: Tipi di risorsa da cercare (deve includere 'item')
    :param user: Utente che esegue la ricerca
    :param level: Livello di accesso richiesto
    :param limit: Numero massimo di risultati
    :param offset: Numero di risultati da saltare
    :returns: Lista di dizionari risultati ricerca
    """
    import logging
    logger = logging.getLogger('girder.plugins.nifti_viewer')

    logger.info(f'=== NIfTI Search Handler Called ===')
    logger.info(f'Query: "{query}"')
    logger.info(f'Types: {types}')
    logger.info(f'Types type: {type(types)}')

    # Check if searching for items (same as DICOM plugin)
    if types != ['item']:
        logger.info(f'Skipping: types is {types}, not ["item"]')
        raise RestException('The nifti search is only able to search in Item.')

    if not isinstance(query, str):
        logger.info(f'Skipping: query is not string: {type(query)}')
        raise RestException('The search query must be a string.')

    # Costruisci condizioni di ricerca complete
    conditions = _buildSearchConditions(query)
    logger.info(f'Built {len(conditions)} search conditions')

    # Costruisci query MongoDB
    search_query = {
        'nifti': {'$exists': True},
        '$or': conditions
    }

    logger.info(f'MongoDB query: {search_query}')

    # Esegui ricerca
    items = Item().findWithPermissions(
        search_query,
        user=user,
        level=level,
        limit=limit,
        offset=offset
    )

    # Filtra risultati con permessi e filtra campi
    filtered_items = []
    for item in items:
        # Usa Item().filter() per filtrare i campi in base ai permessi dell'utente
        filtered_item = Item().filter(item, user)
        filtered_items.append(filtered_item)

        # Log per debug
        if len(filtered_items) <= 3:
            logger.info(f'Result {len(filtered_items)-1}: {item.get("name", "N/A")} (ID: {item["_id"]})')
            if 'nifti' in item and 'meta' in item['nifti']:
                logger.info(f'  Orientation: {item["nifti"]["meta"].get("orientation", "N/A")}')

    logger.info(f'Found {len(filtered_items)} items')

    # Ritorna nel formato corretto per Girder search (stesso formato di DICOM)
    result = {
        'item': filtered_items
    }

    logger.info(f'Returning result with {len(filtered_items)} items')
    return result
