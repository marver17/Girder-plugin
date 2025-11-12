# Quick Start Guide - NIfTI Viewer Plugin

## ⚡ 5-Minute Setup

### Prerequisites
- Girder 5.0.0+ installed and running
- Python 3.8+
- Node.js 16+

### Installation (3 steps)

```bash
# 1. Install backend
cd /workspace/plugins_developer/nifti_viewer
pip install -e .

# 2. Build frontend
cd girder_nifti_viewer/web_client
npm install && npm run build

# 3. Restart Girder
girder serve
```

### First Use (2 minutes)

1. **Upload a NIfTI file**
   - Go to any folder in Girder
   - Click "Upload" → Select your `.nii` or `.nii.gz` file
   - Wait for upload to complete

2. **View the data**
   - Click on the uploaded item
   - Scroll down to see "NIfTI Viewer" section
   - Use controls to explore:
     - **Axial/Coronal/Sagittal** buttons to change view
     - **Slice slider** to navigate
     - **Window Level/Width** to adjust brightness/contrast
     - **Auto W/L** for automatic optimization

### Test with Sample Data

Don't have a NIfTI file? Download a sample:

```bash
# Download sample brain MRI (compressed)
wget https://nifti.nimh.nih.gov/nifti-1/data/avg152T1_LR_nifti.nii.gz
```

Or use any neuroimaging dataset from:
- https://openneuro.org/
- https://www.nitrc.org/
- https://www.cancerimagingarchive.net/

### Common Use Cases

#### 1. Brain MRI Visualization
```python
# After upload, metadata shows:
Dimensions: 91 × 109 × 91
Voxel Size: 2.00 × 2.00 × 2.00 mm
Orientation: RAS
Data Type: int16
```

#### 2. CT Scan with DICOM Metadata
```bash
# Upload both files to same item:
- patient_ct.nii.gz
- patient_ct.json

# Viewer shows NIfTI data + DICOM metadata
```

#### 3. Programmatic Access
```python
from girder.models.item import Item

# Get NIfTI metadata
item = Item().load('item_id', user=user)
nifti_meta = item.get('nifti', {})

print(f"Dimensions: {nifti_meta['meta']['dims']}")
print(f"Orientation: {nifti_meta['meta']['orientation']}")
```

### Troubleshooting

**Viewer not appearing?**
```bash
# Check if plugin is enabled
mongo girder --eval "db.setting.find({key: 'core.plugins_enabled'}).pretty()"

# Should include 'nifti_viewer'
```

**Frontend not loading?**
```bash
# Hard refresh browser
Ctrl + Shift + R  (or Cmd + Shift + R on Mac)
```

**Metadata not extracted?**
```python
# Check Girder logs
girder serve --dev

# Look for: "=== NIfTI Upload Handler Started ==="
```

### Next Steps

- Read full documentation: `README.md`
- Explore window/level presets for different tissue types
- Try different file formats (.nii vs .nii.gz)
- Upload JSON sidecar files for DICOM metadata
- Check `CHANGELOG.md` for latest features

### Support

- Documentation: `/workspace/plugins_developer/nifti_viewer/README.md`
- Issues: Check browser console (F12) for errors
- Logs: Run `girder serve --dev` for detailed output

---

**Pro Tip**: Use Auto W/L button to quickly find optimal window settings for any scan type!
