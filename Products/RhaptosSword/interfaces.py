"""
Zope 3-style interfaces, mostly for marking.

Author: Brian N West (bnwest@rice.edu)
copyright (C) 2010, Rice University. All rights reserved.

This software is subject to the provisions of the GNU Lesser General
Public License Version 2.1 (LGPL).  See LICENSE.txt for details.
"""

from zope.interface import Interface

class IRhaptosSwordWorkspace(Interface):
    """ Marker interface for SWORD service capable Rhaptos worspaces.
    """

class IRhaptosSwordCollection(Interface):
    """ Marker interface for SWORD service capable Rhaptos collections.
    """

class ICollabRequest(Interface):
    """ Collaboration requests should ideally be marked with an interface by
        its containing product, but to make our own code nicer, we shall mark
        it here. """
