## atom.cpy : process sword requests
##parameters=

request = context.REQUEST
response = context.REQUEST.RESPONSE 
sword_tool = context.sword_tool

acceptingSwordRequests = sword_tool.acceptingSwordRequests

member = context.portal_membership.getAuthenticatedMember()
memberId = str(member)
isAnonymousUser = ( memberId == 'Anonymous User' )

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
    if not acceptingSwordRequests:
        response.setStatus('NotFound')
        return response
    elif isAnonymousUser:
        response.setStatus('NotFound')
        return response
    else:
        # zipped word doc is part of the request
        # state.setStatus('ContentCreation')
		type_name = 'module'
		id=context.generateUniqueId(type_name)
		if context.portal_factory.getFactoryTypes().has_key(type_name):
		    o = context.restrictedTraverse('portal_factory/' + type_name + '/' + id)
		    message = None
		    transaction_note('Initiated creation of %s with id %s in %s' % (o.getTypeInfo().getId(), id, context.absolute_url()))
		else:
		    new_id = context.invokeFactory(id=id, type_name=type_name)
		    if new_id is None or new_id == '':
		       new_id = id
		    o=getattr(context, new_id, None)
		    tname = o.getTypeInfo().Title()
		    message = _(u'${tname} has been created.', mapping={u'tname' : tname})
		    transaction_note('Created %s with id %s in %s' % (o.getTypeInfo().getId(), new_id, context.absolute_url()))
		