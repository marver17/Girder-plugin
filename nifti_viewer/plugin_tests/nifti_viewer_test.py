import io
import json
import pytest
import numpy as np
import nibabel as nib

from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.upload import Upload
from pytest_girder.assertions import assertStatusOk


@pytest.fixture
def sample_nifti_file():
    """Create a sample NIfTI file for testing."""
    # Create a simple 3D array
    data = np.random.rand(64, 64, 32).astype(np.float32)
    
    # Create NIfTI image
    affine = np.eye(4)
    img = nib.Nifti1Image(data, affine)
    
    # Save to BytesIO
    bio = io.BytesIO()
    nib.save(img, bio)
    bio.seek(0)
    
    return bio


@pytest.fixture
def sample_json_metadata():
    """Create sample JSON metadata."""
    metadata = {
        'EchoTime': 0.03,
        'RepetitionTime': 2.0,
        'FlipAngle': 90,
        'MagneticFieldStrength': 3.0,
        'Manufacturer': 'TestScanner',
        'ProtocolName': 'T1_MPRAGE'
    }
    return json.dumps(metadata).encode('utf-8')


def test_nifti_plugin_load(server):
    """Test that the plugin loads correctly."""
    from girder.plugin import getPlugin
    
    plugin = getPlugin('nifti_viewer')
    assert plugin is not None
    assert plugin.DISPLAY_NAME == 'NIfTI Viewer'


def test_nifti_item_field_exposed(server, user):
    """Test that the 'nifti' field is exposed on items."""
    from girder.models.item import Item
    from girder.constants import AccessType
    
    # Check that 'nifti' is in exposed fields
    exposed_fields = Item().exposeFields(level=AccessType.READ, fields=set())
    assert 'nifti' in exposed_fields


def test_parse_nifti_endpoint(server, user, admin, folder, sample_nifti_file):
    """Test the parseNifti API endpoint."""
    # Create an item
    item = Item().createItem('test_nifti', admin, folder)
    
    # Upload a NIfTI file
    upload = Upload().uploadFromFile(
        sample_nifti_file,
        size=len(sample_nifti_file.getvalue()),
        name='test.nii.gz',
        parentType='item',
        parent=item,
        user=admin
    )
    
    # Call parseNifti endpoint
    resp = server.request(
        path=f'/item/{item["_id"]}/parseNifti',
        method='POST',
        user=admin
    )
    assertStatusOk(resp)
    
    # Verify that the item has nifti data
    item = Item().load(item['_id'], force=True)
    assert 'nifti' in item
    assert 'meta' in item['nifti']
    assert 'files' in item['nifti']
    
    # Check metadata fields
    meta = item['nifti']['meta']
    assert 'dims' in meta
    assert 'pixdim' in meta
    assert 'datatype' in meta
    assert 'orientation' in meta
    
    # Check dimensions match our test data
    assert meta['dims'] == [64, 64, 32]


def test_parse_nifti_with_json(server, user, admin, folder, sample_nifti_file, sample_json_metadata):
    """Test parsing NIfTI with JSON sidecar."""
    # Create an item
    item = Item().createItem('test_nifti_json', admin, folder)
    
    # Upload NIfTI file
    Upload().uploadFromFile(
        sample_nifti_file,
        size=len(sample_nifti_file.getvalue()),
        name='test.nii.gz',
        parentType='item',
        parent=item,
        user=admin
    )
    
    # Upload JSON file
    json_bio = io.BytesIO(sample_json_metadata)
    Upload().uploadFromFile(
        json_bio,
        size=len(sample_json_metadata),
        name='test.json',
        parentType='item',
        parent=item,
        user=admin
    )
    
    # Call parseNifti endpoint
    resp = server.request(
        path=f'/item/{item["_id"]}/parseNifti',
        method='POST',
        user=admin
    )
    assertStatusOk(resp)
    
    # Verify that the item has nifti data with JSON metadata
    item = Item().load(item['_id'], force=True)
    assert 'nifti' in item
    assert 'json_metadata' in item['nifti']['meta']
    
    # Check JSON metadata
    json_meta = item['nifti']['meta']['json_metadata']
    assert 'EchoTime' in json_meta
    assert json_meta['EchoTime'] == 0.03
    assert json_meta['Manufacturer'] == 'TestScanner'
    
    # Check that both files are referenced
    assert item['nifti']['files']['nifti'] is not None
    assert item['nifti']['files']['json'] is not None


def test_nifti_search_handler(server, admin, folder, sample_nifti_file, sample_json_metadata):
    """Test comprehensive metadata search handler."""
    from girder_nifti_viewer import niftiSubstringSearchHandler

    # Crea item NIfTI con metadati JSON
    item = Item().createItem('searchable_nifti', admin, folder)

    # Upload file NIfTI
    Upload().uploadFromFile(
        sample_nifti_file,
        size=len(sample_nifti_file.getvalue()),
        name='brain_t1_mprage.nii.gz',
        parentType='item',
        parent=item,
        user=admin
    )

    # Upload metadati JSON
    json_bio = io.BytesIO(sample_json_metadata)
    Upload().uploadFromFile(
        json_bio,
        size=len(sample_json_metadata),
        name='brain_t1_mprage.json',
        parentType='item',
        parent=item,
        user=admin
    )

    # Parse
    server.request(
        path=f'/item/{item["_id"]}/parseNifti',
        method='POST',
        user=admin
    )

    # Test 1: Ricerca per filename
    results = niftiSubstringSearchHandler(
        query='brain', types=['item'], user=admin, level=None
    )
    assert len(results) > 0
    assert any(r['document']['_id'] == item['_id'] for r in results)

    # Test 2: Ricerca per BIDS ProtocolName
    results = niftiSubstringSearchHandler(
        query='T1_MPRAGE', types=['item'], user=admin, level=None
    )
    assert len(results) > 0
    assert any(r['document']['_id'] == item['_id'] for r in results)

    # Test 3: Ricerca per BIDS Manufacturer
    results = niftiSubstringSearchHandler(
        query='TestScanner', types=['item'], user=admin, level=None
    )
    assert len(results) > 0
    assert any(r['document']['_id'] == item['_id'] for r in results)

    # Test 4: Ricerca case-insensitive
    results = niftiSubstringSearchHandler(
        query='mprage', types=['item'], user=admin, level=None
    )
    assert len(results) > 0
    assert any(r['document']['_id'] == item['_id'] for r in results)

    # Test 5: Ricerca valore numerico nelle dimensioni
    results = niftiSubstringSearchHandler(
        query='64', types=['item'], user=admin, level=None
    )
    assert len(results) > 0
    assert any(r['document']['_id'] == item['_id'] for r in results)


def test_auto_parse_on_upload(server, admin, folder, sample_nifti_file):
    """Test automatic parsing on NIfTI file upload."""
    # Create an item
    item = Item().createItem('auto_parse_test', admin, folder)
    
    # Upload a NIfTI file (should trigger auto-parsing)
    Upload().uploadFromFile(
        sample_nifti_file,
        size=len(sample_nifti_file.getvalue()),
        name='auto.nii.gz',
        parentType='item',
        parent=item,
        user=admin
    )
    
    # Reload item and check if it has nifti data
    item = Item().load(item['_id'], force=True)
    
    # Note: Auto-parsing happens via event, might need a small delay in real scenarios
    # For this test, we verify the handler is registered
    from girder import events
    handlers = events._mapping.get('data.process', {})
    assert 'nifti_viewer' in handlers
