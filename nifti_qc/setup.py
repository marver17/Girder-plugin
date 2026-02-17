from setuptools import find_packages, setup

setup(
    name="girder-nifti-qc",
    version="0.1.0",
    description="NIfTI Quality Control with MRIQC",
    author="Your Organization",
    author_email="contact@example.com",
    url="https://github.com/yourorg/girder-nifti-qc",
    license="Apache 2.0",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Web Environment",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
    ],
    packages=find_packages(),
    package_data={
        "girder_nifti_qc": [
            "web_client/**/*",
        ],
    },
    include_package_data=True,
    python_requires=">=3.10",
    install_requires=[
        "girder>=5.0.0a14",
        "girder-worker>=5.0.0a14",
        "girder-plugin-worker>=5.0.0a1",
        "girder-client>=5.0.0a14",
        "nibabel>=5.2.0",
        "numpy>=1.24.0",
    ],
    entry_points={
        "girder.plugin": ["nifti_qc = girder_nifti_qc:NiftiQCPlugin"],
        "girder_worker_plugins": ["nifti_qc = girder_nifti_qc.tasks"],
    },
)
