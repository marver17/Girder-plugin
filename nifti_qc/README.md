# NIfTI Quality Control Plugin for Girder

Automated quality assessment of NIfTI neuroimaging files using [MRIQC](https://mriqc.readthedocs.io/) via Girder Worker.

## Features

- 🔬 **Automated QC**: Run MRIQC on NIfTI files with one click
- 📊 **Interactive Reports**: HTML reports with quality metrics
- 🔄 **Background Processing**: Jobs run asynchronously via Girder Worker
- 📈 **Metrics Storage**: QC metrics saved in Girder item metadata
- 🖱️ **Web UI**: Button in item view to launch QC

## Requirements

- Girder >= 5.0.0a14
- Girder Worker >= 5.0.0a14
- Docker (for MRIQC container)
- RabbitMQ (message broker)
- Python >= 3.10

## Installation

### 1. Install Plugin

```bash
cd /workspace/nifti_qc
pip install -e .
```

### 2. Pull MRIQC Docker Image

```bash
docker pull nipreps/mriqc:latest
```

### 3. Restart Girder

```bash
girder serve --host 0.0.0.0 --database mongodb://mongodb:27017/girder
```

### 4. Start Girder Worker

```bash
celery -A girder_worker.app worker -l info
```

## Usage

### Via Web UI

1. Navigate to an item containing a NIfTI file (.nii or .nii.gz)
2. Click **"Run MRIQC Quality Control"** button
3. Monitor job progress in Jobs panel
4. View results in item metadata and download generated reports

### Via REST API

#### Run MRIQC

```bash
curl -X POST http://localhost:8080/api/v1/nifti_qc/{item_id}/run_mriqc \
  -H "Girder-Token: YOUR_TOKEN" \
  -d "participantLabel=001" \
  -d "modality=T1w"
```

#### Quick Check (Fast)

```bash
curl -X POST http://localhost:8080/api/v1/nifti_qc/{item_id}/quick_check \
  -H "Girder-Token: YOUR_TOKEN"
```

#### Get Results

```bash
curl http://localhost:8080/api/v1/item/{item_id}
```

Check `nifti_qc_results` and `nifti_qc_status` fields.

## MRIQC Outputs

### Metrics Stored

- SNR (Signal-to-Noise Ratio)
- CNR (Contrast-to-Noise Ratio)
- FBER (Foreground-Background Energy Ratio)
- EFC (Entropy Focus Criterion)
- FWHM (Full-Width Half-Maximum)
- And many more...

### Generated Files

- `sub-{label}_{modality}.html` - Visual report
- `sub-{label}_{modality}.json` - Quantitative metrics

All files are uploaded to the Girder item.

## Configuration

### Task Parameters

- `participantLabel`: BIDS participant ID (default: '001')
- `modality`: MRI modality - T1w, T2w, bold, etc. (default: 'T1w')
- `timeout`: Max execution time in seconds (default: 1800)

## Troubleshooting

### Docker not found

Ensure Docker is installed and accessible:

```bash
docker --version
```

### MRIQC timeout

Increase timeout parameter:

```python
timeout=3600  # 1 hour
```

### Worker not processing

Check worker logs:

```bash
celery -A girder_worker.app inspect active
```

## Development

### Running Tests

```bash
pytest plugin_tests/
```

### Build Frontend

```bash
cd girder_nifti_qc/web_client
npm install
npm run build
```

## References

- [MRIQC Documentation](https://mriqc.readthedocs.io/)
- [MRIQC on Docker Hub](https://hub.docker.com/r/nipreps/mriqc)
- [Girder Worker](https://girder-worker.readthedocs.io/)

## License

Apache 2.0
