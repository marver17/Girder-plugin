# Sample NIfTI Test Data

This directory contains test data for the NIfTI viewer plugin.

## Test Files

You can add sample NIfTI files here for manual testing:

- `sample.nii.gz` - Example NIfTI file
- `sample.json` - Example JSON metadata (BIDS format)

## Generating Test Data

To generate a simple test NIfTI file:

```python
import numpy as np
import nibabel as nib

# Create random 3D data
data = np.random.rand(64, 64, 32).astype(np.float32)

# Create NIfTI image with identity affine
affine = np.eye(4)
img = nib.Nifti1Image(data, affine)

# Save
nib.save(img, 'sample.nii.gz')
```

To create a sample JSON metadata file:

```json
{
  "EchoTime": 0.03,
  "RepetitionTime": 2.0,
  "FlipAngle": 90,
  "MagneticFieldStrength": 3.0,
  "Manufacturer": "TestScanner",
  "ProtocolName": "T1_MPRAGE"
}
```
