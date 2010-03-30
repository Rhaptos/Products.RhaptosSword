<xsl:stylesheet version="1.0"
    xmlns:mets="http://www.loc.gov/METS/"
    xmlns:epdcx="http://purl.org/eprint/epdcx/2006-11-16/"
    xmlns:md="http://cnx.rice.edu/mdml/0.4"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform">

<xsl:template match="/">
    <metadata>
        <xsl:apply-templates select="@*|node()"/>
    </metadata>
</xsl:template>

<!-- Simple, brain-dead conversions -->
<xsl:template match="epdcx:statement[@epdcx:propertyURI='http://purl.org/dc/elements/1.1/title']">
    <md:title><xsl:value-of select="epdcx:valueString/text()"/></md:title>
</xsl:template>

<xsl:template match="epdcx:statement[@epdcx:propertyURI='http://purl.org/dc/terms/abstract']">
    <md:abstract><xsl:value-of select="epdcx:valueString/text()"/></md:abstract>
</xsl:template>

<xsl:template match="epdcx:statement[@epdcx:propertyURI='http://purl.org/dc/elements/1.1/language']">
    <md:language><xsl:value-of select="epdcx:valueString/text()"/></md:language>
</xsl:template>


<!-- Keywords aren't provided as XML elements, so we need to extract them from the bibliographicCitation string. Ugly, but works -->
<xsl:template match="epdcx:statement[@epdcx:propertyURI='http://purl.org/eprint/terms/bibliographicCitation']">
    <xsl:variable name="keywords-string" select="substring-before(substring-after(epdcx:valueString/text(), 'keywords = {'), '},')"/>
    <md:keywords>
        <xsl:call-template name="util.keyword-splitter">
            <xsl:with-param name="str" select="$keywords-string"/>
        </xsl:call-template>
    </md:keywords>
</xsl:template>

<!-- Recursively split the '; ' separated keywords -->
<xsl:template name="util.keyword-splitter">
    <xsl:param name="str"/>
    <xsl:param name="split-on">; </xsl:param>
    <xsl:choose>
        <xsl:when test="contains($str, $split-on)">
            <md:keyword><xsl:value-of select="substring-before($str, $split-on)"/></md:keyword>
            <xsl:call-template name="util.keyword-splitter">
                <xsl:with-param name="str" select="substring-after($str, $split-on)"/>
            </xsl:call-template>
        </xsl:when>
        <xsl:otherwise>
            <md:keyword><xsl:value-of select="$str"/></md:keyword>
        </xsl:otherwise>
    </xsl:choose>
</xsl:template>

<!-- All other elements are ignored -->
<xsl:template match="@*|node()">
    <xsl:apply-templates/>
</xsl:template>


</xsl:stylesheet>
