"""Keystone loads its bundled DLL directly; omit its distutils fallback.

Do not exclude distutils globally: PyInstaller's alias hook expects to own that
name. Scope the exclusion to Keystone's optional legacy discovery import.
"""
excludedimports = ['distutils']
