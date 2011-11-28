from xml.dom.minidom import parse

from zope.interface import implements
from zope.security.interfaces import Forbidden

from Products.CMFCore.utils import getToolByName

from rhaptos.atompub.plone.exceptions import PreconditionFailed
from rhaptos.atompub.plone.browser.atompub import PloneFolderAtomPubAdapter
from rhaptos.atompub.plone.browser.atompub import getSiteEncoding 


from Products.RhaptosSword.interfaces import ILensAtomPubServiceAdapter


class LensAtomPubAdapter(PloneFolderAtomPubAdapter):
    implements(ILensAtomPubServiceAdapter)
    
    encoding = ''

    def __call__(self):
        lens = self.context
        if not lens.isOpen():
            # get attrs
            encoding = self.getEncoding() 
            content_tool = getToolByName(self.context, 'content')
            dom = parse(self.request.get('BODYFILE'))
            path = lens.getPhysicalPath()
            
            # get all the modules
            entries = dom.getElementsByTagName('entry')
            for entry in entries:
                contentId = entry.getElementsByTagName('id')
                if not contentId:
                    raise PreconditionFailed('You must supply a module id.')

                contentId = contentId[0].firstChild.toxml().encode(encoding)
                if contentId:
                    if contentId in lens.objectIds():
                        raise Forbidden(
                            'Module %s is already part of the lens %s' 
                            %(contentId, lens.getId())) 

                    module = content_tool.getRhaptosObject(contentId)
                    if module:
                        elements = \
                            entry.getElementsByTagName('rhaptos:versionStart')
                        versionStart = elements and elements[0].firstChild.toxml()
                        version = versionStart.encode(encoding) or 'latest'

                        namespaceTags = []

                        tags = entry.getElementsByTagName('rhaptos:tag')
                        tags = [tag.firstChild.toxml().encode(encoding) for tag in tags]
                        tags = ' '.join(tags)

                        comments = entry.getElementsByTagName('rhaptos:comment')
                        comments = \
                            [comment.firstChild.toxml().encode(encoding) \
                             for comment in comments]
                        comments = '\n\r'.join(comments)

                        lens.lensAdd(
                            lensPath=path, 
                            contentId=contentId, 
                            version=version, 
                            namespaceTags=namespaceTags, 
                            tags=tags,
                            comment=comments,
                        )            
                    else:
                        raise Exception('Not found')
            return lens
        else:
            # actually we should raise and error and use the decorators
            return None

    def getEncoding(self):
        """ Get the encoding to use.
            We prefer the site encoding, but will fall back to utf-8
        """
        if not self.encoding:
            self.encoding = getSiteEncoding(self.context)
        return self.encoding
    



