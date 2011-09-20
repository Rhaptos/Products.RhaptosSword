import string
from unicodedata import normalize, decomposition
import re

# On OpenBSD string.whitespace has a non-standard implementation
# See http://dev.plone.org/plone/ticket/4704 for details
whitespace = ''.join([c for c in string.whitespace if ord(c) < 128])
allowed = string.ascii_letters + string.digits + string.punctuation + whitespace

CHAR = {}
NULLMAP = ['' * 0x100]
UNIDECODE_LIMIT = 0x0530

FILENAME_REGEX = re.compile(r"^(.+)\.(\w{,4})$")
IGNORE_REGEX = re.compile(r"['\"]")
DANGEROUS_CHARS_REGEX = re.compile(r"[!$%&()*+,/:;<=>?@\\^{|}\[\]~`]+")
MULTIPLE_DASHES_REGEX = re.compile(r"\-+")
EXTRA_DASHES_REGEX = re.compile(r"(^\-+)|(\-+$)")
UNDERSCORE_START_REGEX = re.compile(r"(^_+)(.*)$")

def baseNormalize(text):
    """
    This method is used for normalization of unicode characters to the base ASCII
    letters. Output is ASCII encoded string (or char) with only ASCII letters,
    digits, punctuation and whitespace characters. Case is preserved.

      >>> baseNormalize(123)
      '123'

      >>> baseNormalize(u'a\u0fff')
      'afff'

      >>> baseNormalize(u"foo\N{LATIN CAPITAL LETTER I WITH CARON}")
      'fooI'

      >>> baseNormalize(u"\u5317\u4EB0")
      '53174eb0'
    """
    if not isinstance(text, basestring):
        # This most surely ends up in something the user does not expect
        # to see. But at least it does not break.
        return repr(text)

    text = text.strip()

    res = []
    for ch in text:
        if ch in allowed:
            # ASCII chars, digits etc. stay untouched
            res.append(ch)
        else:
            ordinal = ord(ch)
            if ordinal < UNIDECODE_LIMIT:
                h = ordinal >> 8
                l = ordinal & 0xff

                c = CHAR.get(h, None)

                if c == None:
                    try:
                        mod = __import__('unidecode.x%02x'%(h), [], [], ['data'])
                    except ImportError:
                        CHAR[h] = NULLMAP
                        res.append('')
                        continue

                    CHAR[h] = mod.data

                    try:
                        res.append( mod.data[l] )
                    except IndexError:
                        res.append('')
                else:
                    try:
                        res.append( c[l] )
                    except IndexError:
                        res.append('')

            elif decomposition(ch):
                normalized = normalize('NFKD', ch).strip()
                # string may contain non-letter chars too. Remove them
                # string may result to more than one char
                res.append(''.join([c for c in normalized if c in allowed]))

            else:
                # hex string instead of unknown char
                res.append("%x" % ordinal)

    return ''.join(res).encode('ascii')


def cropName(base, maxLength):
    """ Chop it off at the nearest dash, or at maxLength. """
    baseLength = len(base)
    
    index = baseLength
    while index > maxLength:
        index = base.rfind('-', 0, index)

    if index == -1 and baseLength > maxLength:
        base = base[:maxLength]

    elif index > 0:
        base = base[:index]

    return base

def normalizeFilename(text):
    """
    Returns a normalized text. text has to be a unicode string and locale
    should be a normal locale, for example: 'pt_BR', 'sr@Latn' or 'de'
    """

    # Preserve filename extensions
    text = baseNormalize(text)

    # Remove any leading underscores
    m = UNDERSCORE_START_REGEX.match(text)
    if m is not None:
        text = m.groups()[1]

    base = text
    ext  = ''

    m = FILENAME_REGEX.match(text)
    if m is not None:
        base = m.groups()[0]
        ext  = m.groups()[1]

    base = IGNORE_REGEX.sub('', base)
    base = DANGEROUS_CHARS_REGEX.sub('-', base)
    base = EXTRA_DASHES_REGEX.sub('', base)
    base = MULTIPLE_DASHES_REGEX.sub('-', base)

    base = cropName(base, 1023)

    if ext != '':
        base = base + '.' + ext

    return base
