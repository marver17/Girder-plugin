import os
import subprocess
from setuptools import find_packages, setup
from setuptools.command.install import install
from setuptools.command.develop import develop


class BuildFrontend:
    """Mixin class to build frontend during installation."""

    def run_frontend_build(self):
        """Build the frontend using npm."""
        frontend_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'girder_nifti_viewer',
            'web_client'
        )

        if not os.path.exists(frontend_dir):
            print('Frontend directory not found, skipping build')
            return

        print('Building frontend...')
        try:
            # Install npm dependencies
            subprocess.check_call(['npm', 'install'], cwd=frontend_dir)
            # Build frontend
            subprocess.check_call(['npm', 'run', 'build'], cwd=frontend_dir)
            print('Frontend build completed successfully')
        except subprocess.CalledProcessError as e:
            print(f'Warning: Frontend build failed: {e}')
            print('You may need to build the frontend manually:')
            print(f'  cd {frontend_dir}')
            print('  npm install')
            print('  npm run build')
        except FileNotFoundError:
            print('Warning: npm not found. Please install Node.js and npm.')
            print('Frontend must be built manually.')


class InstallWithFrontend(BuildFrontend, install):
    """Custom install command that builds frontend."""

    def run(self):
        self.run_frontend_build()
        install.run(self)


class DevelopWithFrontend(BuildFrontend, develop):
    """Custom develop command that builds frontend."""

    def run(self):
        self.run_frontend_build()
        develop.run(self)


# Read long description from README
with open('README.md', 'r', encoding='utf-8') as f:
    long_description = f.read()


# Perform the install
setup(
    name='girder-nifti-viewer',
    version='1.1.0',
    description='View NIfTI neuroimaging files in Girder with BIDS support and advanced metadata search',
    long_description=long_description,
    long_description_content_type='text/markdown',
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
        'Programming Language :: Python :: 3.11',
        'Topic :: Scientific/Engineering :: Medical Science Apps.',
        'Topic :: Scientific/Engineering :: Visualization',
    ],
    keywords='girder nifti neuroimaging bids medical-imaging viewer',
    include_package_data=True,
    packages=find_packages(exclude=['plugin_tests']),
    zip_safe=False,
    python_requires='>=3.8',
    install_requires=[
        'girder>=4.0.0',
        'nibabel>=4.0.0',
        'numpy>=1.20.0',
    ],
    extras_require={
        'test': [
            'pytest>=6.0',
            'pytest-girder>=3.0',
        ],
    },
    entry_points={
        'girder.plugin': [
            'nifti_viewer = girder_nifti_viewer:NiftiViewerPlugin',
        ]
    },
    cmdclass={
        'install': InstallWithFrontend,
        'develop': DevelopWithFrontend,
    },
)
