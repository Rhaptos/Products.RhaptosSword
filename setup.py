from setuptools import setup, find_packages
import os

version = '1.0'

setup(name='Products.RhaptosSword',
      version=version,
      description="Rhaptos product to import Word documents via the Sword protocol.",
      long_description=open("README.txt").read() + "\n" +
                       open(os.path.join("docs", "HISTORY.txt")).read(),
      # Get more strings from
      # http://pypi.python.org/pypi?%3Aaction=list_classifiers
      classifiers=[
        "Programming Language :: Python",
        ],
      keywords='',
      author='Rhaptos team',
      author_email='rhaptos@cnx.org',
      url='http://rhaptos.org',
      license='GPL',
      packages=find_packages(exclude=['ez_setup']),
      namespace_packages=['Products'],
      include_package_data=True,
      zip_safe=False,
      install_requires=[
          'setuptools',
          # -*- Extra requirements: -*-
      ],
      entry_points="""
      # -*- Entry points: -*-
      """,
      )
