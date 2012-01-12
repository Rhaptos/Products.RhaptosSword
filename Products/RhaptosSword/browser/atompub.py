import transaction
from xml.dom.minidom import parse

from ZTUtils import make_query
from zope.interface import implements
from zope.security.interfaces import Forbidden
from zExceptions import Unauthorized

from Products.CMFCore.utils import getToolByName

from rhaptos.atompub.plone.exceptions import PreconditionFailed
from rhaptos.atompub.plone.browser.atompub import PloneFolderAtomPubAdapter
from rhaptos.atompub.plone.browser.atompub import getSiteEncoding 


from Products.RhaptosSword.interfaces import ILensAtomPubServiceAdapter


class LensAtomPubAdapter(PloneFolderAtomPubAdapter):
    implements(ILensAtomPubServiceAdapter)
    
    encoding = ''

    def getEncoding(self):
        """ Get the encoding to use.
            We prefer the site encoding, but will fall back to utf-8
        """
        if not self.encoding:
            self.encoding = getSiteEncoding(self.context)
        return self.encoding
    
    def __call__(self):
        lens = self.context
        pmt = getToolByName(self.context, 'portal_membership')
        authenticated_member = pmt.getAuthenticatedMember()
        if authenticated_member.getId() != lens.Creator():
            msg = (
                'The account, %s, is not allowed to add to the lens '
                'located at %s since it is not an owner of this lens.' % (
                authenticated_member.getId(), lens.absolute_url())
                )
            raise Unauthorized(msg)

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
                        versionStart = ''
                        if elements and elements[0].hasChildNodes():
                            versionStart = elements[0].firstChild.toxml()
                            versionStart = versionStart.encode(encoding) or '1'
                        
                        elements = \
                            entry.getElementsByTagName('rhaptos:versionStop')
                        versionStop = ''
                        if elements and elements[0].hasChildNodes():
                            versionStop = elements[0].firstChild.toxml()
                            versionStop = versionStop.encode(encoding) or 'latest'

                        namespaceTags = []

                        tags = entry.getElementsByTagName('rhaptos:tag')
                        tags = [tag.firstChild.toxml().encode(encoding) for tag in tags]
                        tags = ' '.join(tags)

                        elements = entry.getElementsByTagName('rhaptos:inclusive')
                        inclusive = ''
                        if elements and elements[0].hasChildNodes():
                            inclusive = elements[0].firstChild.toxml().encode(encoding)
                            inclusive = inclusive == 'True' and True or False

                        comments = entry.getElementsByTagName('rhaptos:comment')
                        comments = \
                            [comment.firstChild.toxml().encode(encoding) \
                             for comment in comments]
                        comments = '\n\r'.join(comments)

                        self.lensAdd(
                            lensPath=path, 
                            contentId=contentId, 
                            versionStart=versionStart, 
                            versionStop=versionStop,
                            namespaceTags=namespaceTags, 
                            tags=tags,
                            comment=comments,
                            inclusive=inclusive
                        )            
                    else:
                        raise Exception('Not found')
            return lens
        else:
            # actually we should raise and error and use the decorators
            return None

    def lensAdd(self, lensPath, contentId, versionStart, versionStop='latest', namespaceTags=[],
                tags='', comment='', inclusive=True, approved=False, approved_marker=False,
                implicit=True):

        """ Add content to a specific lens.
            Copied and adapted from:
            Products.Lensmaker/Products/Lensmaker/skins/lensmaker/lensAdd.py
        """
        try:
            lens = self.context.restrictedTraverse(lensPath)
            tags = tags.split()
            # not really necessary since we check above if the module has been
            # added to the lens before and stop if it was. Just leaving it in case.
            entry = lens._getOb(contentId, None)
            if entry is None:
                lens.invokeFactory(id=contentId, type_name="SelectedContent")
                entry = lens[contentId]
            attrs = dict(contentId=contentId,
                         versionStart=versionStart,
                         versionStop=versionStop,
                         namespaceTags=namespaceTags,
                         tags=tags,
                         comment=comment,
                         inclusive=inclusive,
                         implicit=implicit)
            if approved_marker:
                attrs['approved'] = approved
            entry.update(**attrs)

            lens.setModificationDate()
            lens.reindexObject(idxs=['count', 'modified'])

        except KeyError:
            return "Error: no such lens"

        return "Sucessful."


