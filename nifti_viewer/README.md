# NIfTI Viewer Plugin for Girder

[![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)](CHANGELOG.md)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)

A plugin for viewing and analyzing NIfTI (Neuroimaging Informatics Technology Initiative) files in Girder, with full BIDS metadata support.

## Features

### Backend
- **Automatic parsing** of NIfTI files (.nii, .nii.gz) on upload
- **Complete NIfTI metadata extraction**: dimensions, voxel size, data type, orientation, units, affine matrices
- **Full BIDS support**: parsing of JSON sidecar files with DICOM/BIDS metadata
- **Advanced metadata search**: full-text search across 35+ metadata fields
  - NIfTI header fields (orientation, datatype, dimensions, spacing, units, etc.)
  - BIDS JSON metadata (ProtocolName, Manufacturer, SeriesDescription, etc.)
  - File names
- **REST API** for manual parsing and metadata retrieval
- **Automatic tracking** of NIfTI and JSON file associations

### Frontend
- **Interactive 3D/2D viewer** based on [Niivue](https://github.com/niivue/niivue)
- **Multi-planar visualization**: axial, coronal, sagittal with real-time orientation switching
- **Advanced windowing controls**:
  - Manual window level and width adjustment
  - Predefined presets (brain, bone, lung, soft tissue)
  - Auto-levels with percentile calculation
- **Advanced navigation**:
  - Slider for slice navigation
  - Mouse wheel support for zoom and slice navigation
  - Playback controls with adjustable speed
- **Complete metadata display**:
  - NIfTI header metadata
  - Formatted BIDS JSON metadata
  - Real-time volume information
- **Responsive** and modern interface

### Metadata Search

The plugin offers a dedicated "**NIfTI metadata search**" mode accessible from Girder's search bar.

**Search examples:**
- `T1` - Find all T1 scans (from ProtocolName, SeriesDescription)
- `MPRAGE` - Find MPRAGE sequences
- `Siemens` - Find scans by scanner manufacturer
- `RAS` - Find by anatomical orientation
- `256` - Find scans with specific dimensions
- `3.0` - Find 3T scans

**Searchable fields:**
- **NIfTI Header**: orientation, datatype, dimensions, pixelSpacing, units, time_units, file_type
- **BIDS JSON**: ProtocolName, SeriesDescription, Manufacturer, ManufacturersModelName, MagneticFieldStrength, ImageType, InstitutionName, and many more
- **File names**: also searches in .nii/.nii.gz/.json file names

Search is **case-insensitive** and supports **partial matches** (substring).

## Requirements

- **Girder**: >= 4.0.0
- **Python**: >= 3.8
- **Node.js**: >= 14 (for frontend build)
- **npm**: >= 6

### Python Dependencies
- nibabel >= 4.0.0
- numpy >= 1.20.0

## Installation

### Method 1: Automatic Installation (Recommended)

This method installs the backend and automatically builds the frontend:

```bash
# Clone the repository (or copy the files)
cd /path/to/project/nifti_viewer

# Install with automatic frontend build
pip install .

# Restart Girder
girder serve
```

The frontend will be automatically built during installation.

### Method 2: Developer Installation (Editable)

For active development with code modifications:

```bash
# Install in editable mode
pip install -e .

# Build the frontend
cd girder_nifti_viewer/web_client
npm install
npm run build
cd ../..

# Restart Girder
girder serve
```

### Method 3: Manual Installation (Legacy)

```bash
# 1. Install the backend
pip install -e .

# 2. Build the frontend
cd girder_nifti_viewer/web_client
npm install
npm run build

# 3. Restart Girder
girder serve
```

## Usage

### Upload NIfTI Files

1. Upload `.nii` or `.nii.gz` files to a Girder item
2. Metadata parsing happens **automatically**
3. Optionally, upload a JSON sidecar file with the same base name (e.g., `brain.nii.gz` + `brain.json`)

### Manual Parsing

If a file is not automatically processed:

1. Open the item in Girder
2. Click the **"Parse NIfTI"** button in the actions menu
3. Metadata will be extracted and the viewer will appear

### Metadata Search

1. Go to Girder's search bar
2. Select **"NIfTI metadata search"** from the mode dropdown
3. Enter your query (e.g., "T1", "MPRAGE", "Siemens")
4. Results will appear in real-time

## REST API

### `POST /api/v1/item/{id}/parseNifti`

Performs manual parsing of a NIfTI item.

**Parameters:**
- `id` (path): Girder item ID

**Response:**
```json
{
  "_id": "...",
  "name": "brain_scan",
  "nifti": {
    "meta": {
      "dimensions": [256, 256, 170],
      "pixelSpacing": [1.0, 1.0, 1.0],
      "orientation": "RAS",
      "dataType": "float32",
      "json_metadata": {
        "ProtocolName": "T1_MPRAGE",
        "Manufacturer": "Siemens"
      }
    },
    "files": [...]
  }
}
```

## Metadata Structure

Metadata is saved in the item with the following structure:

```javascript
{
  "nifti": {
    "meta": {
      // NIfTI Header
      "dimensions": [256, 256, 170],
      "pixelSpacing": [1.0, 1.0, 1.0],
      "dataType": "float32",
      "orientation": "RAS",
      "units": "mm",
      "time_units": "sec",
      "file_type": "NIfTI-1",
      "qform_code": 1,
      "sform_code": 1,
      "affine": [[...], [...], [...], [...]],
      "voxelSize": 1.0,

      // BIDS JSON Metadata (if present)
      "json_metadata": {
        "RepetitionTime": 2.0,
        "EchoTime": 0.03,
        "ProtocolName": "T1_MPRAGE",
        "Manufacturer": "Siemens",
        "MagneticFieldStrength": 3.0,
        ...
      }
    },
    "files": [
      {
        "id": "file_id",
        "name": "brain.nii.gz",
        "size": 12345678,
        "created": "2025-12-07T..."
      }
    ]
  }
}
```

## Development

### Project Structure

```
nifti_viewer/
├── girder_nifti_viewer/           # Plugin source code
│   ├── __init__.py                # Python backend (parsing, API, search)
│   └── web_client/                # Frontend
│       ├── main.js                # Entry point, search registration
│       ├── views/
│       │   ├── NiftiView.js       # Main viewer controller
│       │   ├── NiftiSliceImageWidget.js  # Image rendering
│       │   └── NiftiFileModel.js  # File download and caching
│       ├── templates/             # Pug templates
│       ├── stylesheets/           # Stylus styles
│       └── constants/             # Configuration
├── plugin_tests/                  # Test suite
│   └── nifti_viewer_test.py
├── setup.py                       # Installation configuration
├── CHANGELOG.md                   # Change history
└── README.md                      # This file
```

### Running Tests

```bash
# Install test dependencies
pip install -e .[test]

# Run tests
pytest plugin_tests/
```

### Recompiling the Frontend

During development, after frontend modifications:

```bash
cd girder_nifti_viewer/web_client
npm run build
# Restart Girder
```

## BIDS Compatibility

The plugin fully supports the [BIDS (Brain Imaging Data Structure)](https://bids-specification.readthedocs.io/) standard:

- Automatic parsing of JSON sidecar files
- All common BIDS fields are indexed for search
- Formatted BIDS metadata display in the viewer

### Supported BIDS Fields

**Acquisition:**
- ProtocolName, SeriesDescription, SequenceName
- RepetitionTime, EchoTime, FlipAngle
- MagneticFieldStrength, ImageType

**Hardware:**
- Manufacturer, ManufacturersModelName
- DeviceSerialNumber, StationName, SoftwareVersions

**Institution:**
- InstitutionName, InstitutionAddress, InstitutionalDepartmentName

**Processing:**
- ConversionSoftware, ConversionSoftwareVersion

And many more...

## License

Apache Software License 2.0

## Acknowledgments

- [Niivue](https://github.com/niivue/niivue) - NIfTI rendering library
- [nibabel](https://nipy.org/nibabel/) - Python library for NIfTI parsing
- [BIDS](https://bids-specification.readthedocs.io/) - Brain Imaging Data Structure standard
