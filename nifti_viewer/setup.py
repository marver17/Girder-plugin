from setuptools import find_packages, setup


# perform the install
setup(
    name='girder-nifti-viewer',
    version='1.0.0',
    description='View NIfTI neuroimaging files in the browser',
    author='Your Organization',
    author_email='contact@example.com',
    url='https://github.com/yourorg/girder-nifti-viewer',
    license='Apache Software License 2.0',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Web Environment',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
    ],
    include_package_data=True,
    packages=find_packages(exclude=['plugin_tests']),
    zip_safe=False,
    install_requires=[
        'girder>=4.0.0',
        'nibabel>=4.0.0',
        'numpy>=1.20.0',
    ],
    entry_points={
        'girder.plugin': [
            'nifti_viewer = girder_nifti_viewer:NiftiViewerPlugin',
        ]
    },
)
