from StringIO import StringIO
from xml.dom.minidom import parse
from email import message_from_file
from Products.CMFCore.utils import getToolByName
from rhaptos.swordservice.plone.exceptions import MaxUploadSizeExceeded

def splitMultipartRequest(request):
    """ This is only to be used for multipart uploads. The first
        part is the atompub bit, the second part is the payload. """
    request.stdin.seek(0)
    message = message_from_file(request.stdin)
    atom, payload = message.get_payload()

    # Call get_payload with decode=True, so it can handle the transfer
    # encoding for us, if any.
    atom = atom.get_payload(decode=True)
    content_type = payload.get_content_type()
    payload = payload.get_payload(decode=True)
    dom = parse(StringIO(atom))
    return dom, payload, content_type


def checkUploadSize(context, fp):
    """ Check size of file handle. """
    maxupload = getToolByName(context, 'sword_tool').getMaxUploadSize()
    if hasattr(fp, 'seek'):
        fp.seek(0, 2)
        size = fp.tell()
        fp.seek(0)
    else:
        size = len(fp)
    if size > maxupload:
        raise MaxUploadSizeExceeded("Maximum upload size exceeded",
            "The uploaded content is larger than the allowed %d bytes." % maxupload)

