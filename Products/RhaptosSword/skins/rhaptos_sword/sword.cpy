## atom.cpy : process sword requests
##parameters=
from Products.CNXMLTransforms.helpers import OOoImportError, doTransform, makeContent
import transaction
from AccessControl import getSecurityManager

# allowed in SwordTool. Used for detecting import errors
from zipfile import BadZipfile

request = context.REQUEST
response = context.REQUEST.RESPONSE 
sword_tool = context.sword_tool

acceptingSwordRequests = sword_tool.acceptingSwordRequests

member = context.portal_membership.getAuthenticatedMember()
memberId = str(member)
isAnonymousUser = context.portal_membership.isAnonymousUser()

method = request['REQUEST_METHOD']

context.plone_log("method is %s." % method)
context.plone_log("member is %s." % memberId)
context.plone_log("Accepting Sword Request? %s." % str(acceptingSwordRequests))

if method == "GET":
    # service request
    if acceptingSwordRequests:
        state.setStatus('ServiceDiscovery')
        return state.set(context=context)
    else:
        response.setStatus('NotFound')
        return response
elif method == "POST":
    # content post
    context.plone_log("SWORD Import for %s: Started." % memberId)
    if isAnonymousUser:
        context.plone_log("SWORD Import for %s: Aborted. Anonymous not allowed and sending custom Unauthorized response." % memberId)
        response.setStatus('Unauthorized')
        state.setStatus('SwordAnonymousPost')
        return state.set(context=context)
    elif not acceptingSwordRequests:
        context.plone_log("SWORD Import for %s: Aborted. Not accepting SWORD Requests." % memberId)
        response.setStatus('NotFound')
        return response
    else:
        # zipped word doc is part of the request
        # state.setStatus('ContentCreation')
        # If this folder allows Modules to be created, use it. Otherwise, use the user's home folder
        cntxt = member.getHomeFolder()
        for t in context.filtered_meta_types(member):
            if t['name'] == 'Module Editor':
              cntxt = context
        context.plone_log("SWORD Import for %s: Creating module in %s ." % (memberId, cntxt))
        type_name = 'Module'
        id=cntxt.generateUniqueId(type_name)
        new_id = cntxt.invokeFactory(id=id, type_name=type_name)
        if new_id is None or new_id == '':
           new_id = id
        rme=getattr(cntxt, new_id, None)
        if rme is not None: context.plone_log("SWORD Import for %s: Created module id=%s ." % (memberId, new_id))
        # Perform the import
        try:
            text = context.REQUEST['BODY']
            kwargs = {'original_file_name':'sword-import-file', 'user_name':getSecurityManager().getUser().getUserName()}
            text, subobjs, meta = doTransform(rme, "sword_to_folder", text, meta=1, **kwargs)
            context.plone_log("SWORD Import for %s with id=%s: Transformed metadata and transformed document to cnxml." % (memberId, new_id))
            if text:
                rme.manage_delObjects([rme.default_file,])
                rme.invokeFactory('CNXML Document', rme.default_file, file=text, idprefix='zip-')
            makeContent(rme, subobjs)
            # Parse the returned mdml and set attributes up on the ModuleEditor object
            rme.updateMdmlStr(meta.get('mdml'))
            context.plone_log("SWORD Import for %s with id=%s: Completed." % (memberId, new_id))
            response.setStatus('Created')
            return state.set(status='SwordImportSuccess', context=rme)

        except OOoImportError, e:
            transaction.abort()
            context.plone_log("SWORD Import for %s with id=%s: Aborted. There were problems transforming the openoffice or word document." % (memberId, new_id))
            message = context.translate("message_could_not_import", {"errormsg":e}, domain="rhaptos",
                                        default="Could not import file. %s" % e)
            response.setStatus('BadRequest')
            return state.set(status='SwordImportError', portal_status_message=message)
        except BadZipfile, e:
            transaction.abort()
            context.plone_log("SWORD Import for %s with id=%s: Aborted. There were problems with the uploaded zip file." % (memberId, new_id))
            response.setStatus('BadRequest')
            return state.set(status='SwordErrorZip')
