from setuptools import find_packages, setup


# perform the install
setup(
    name='girder-oauth',
    version='1.0.0',
    description='Allow users to login via supported OAuth2 providers.',
    author='Kitware, Inc.',
    author_email='kitware@kitware.com',
    url='http://girder.readthedocs.io/en/latest/plugins.html#oauth-login',
    license='Apache 2.0',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Web Environment',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
    ],
    include_package_data=True,
    python_requires='>=3.9',
    packages=find_packages(exclude=['plugin_tests']),
    zip_safe=False,
    install_requires=[
        'girder>=3',
        'msal',
        'pyjwt>=2,<3',
    ],
    entry_points={
        'girder.plugin': [
            'oauth = girder_oauth:OAuthPlugin'
        ]
    }
)
