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

                        self.lensAdd(
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
    
    def lensAdd(self, lensPath, contentId, version, namespaceTags=[], tags='',
                comment='', approved=False, approved_marker=False, implicit=True,
                returnTo=None, batched=False):

        """ Add content to a specific lens.
            Copied and adapted from:
            Products.Lensmaker/Products/Lensmaker/skins/lensmaker/lensAdd.py
        """
        lenstool = self.context.lens_tool
        history = self.context.content.getHistory(contentId)

        # version defaults
        versionStart = version  # current
        versionStop = 'latest'  # latest
        cmpVersion = [int(x) for x in version.split('.')]

        try:
            if lensPath == '__new__':
              # go to creation...
              querystr = make_query(contentId=contentId,
                                    namespaceTags=namespaceTags,
                                    tags=tags, comment=comment,
                                    versionStart=versionStart,
                                    versionStop=versionStop,
                                    implicit=implicit,
                                    approved=approved,
                                    returnTo=returnTo)
              self.context.REQUEST.RESPONSE.redirect('/create_lens?%s' % querystr)
              return "Need to create"
            else:
              lens = self.context.restrictedTraverse(lensPath)
              if self.context.portal_factory.isTemporary(lens):
                  # make concrete...
                  newid = getattr(lens, 'suggestId', lambda: None)() or lens.getId()
                  lens = self.context.portal_factory.doCreate(lens, newid)

            tags = tags.split()
            entry = getattr(lens, contentId, None)
            made = False
            if entry is None:
                lens.invokeFactory(id=contentId, type_name="SelectedContent")
                entry = lens[contentId]
                made = True

            # unchosen version behavior:
            #  - if end is latest, do nothing
            #  - if end <= current, do nothing
            #  - if end > current, set version to current
            # we don't pay attention to beginning ranges. versionStart is left alone
            # (except in creation, of course)
            if not made:  # we will accept the values above for new content
                origStart = entry.getRawVersionStart()  # string version, like '1.1'
                versionStart = origStart

                origStop = entry.getRawVersionStop()
                if origStop:   # latest is (), so only true for explicit stop versions
                    cmpOrigStop = entry.getVersionStop()     # list version, like [1,1]
                    if cmpVersion > cmpOrigStop:
                        versionStop = version      # current is newer, so set stop to current
                    else:
                        versionStop = origStop     # otherwise, leave it alone

            # Only set approved if it is present on the form. This is determined
            # by checking approved_marker.
            attrs = dict(contentId=contentId,
                         versionStart=versionStart,
                         versionStop=versionStop,
                         namespaceTags=namespaceTags,
                         tags=tags,
                         comment=comment,
                         implicit=implicit)
            if approved_marker:
                attrs['approved'] = approved
            entry.update(**attrs)

            lens.setModificationDate()
            lens.reindexObject(idxs=['count', 'modified'])

        except KeyError:
            return "Error: no such lens"

        return "Sucessful."


