"""Draw the visible marker and add the two metadata formats from SPEC-342."""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin


NOTICE = "AI 생성 · 마롱이"
XMP = """<x:xmpmeta xmlns:x="adobe:ns:meta/">
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/">
<Iptc4xmpExt:DigitalSourceType rdf:resource="http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"/>
</rdf:Description></rdf:RDF></x:xmpmeta>"""


def marked_png(source, font_file):
    with Image.open(source if not isinstance(source, bytes) else BytesIO(source)) as original:
        canvas = original.convert("RGBA")
    margin = max(2, round(min(canvas.size) * .018))
    target = max(1, round(min(canvas.size) * .03))
    font = ImageFont.truetype(str(font_file), size=target)
    _, top, _, bottom = font.getbbox(NOTICE)
    if bottom > top:
        font = ImageFont.truetype(str(font_file), size=max(1, round(target * target / (bottom - top))))

    layer = Image.new("RGBA", canvas.size)
    position = (canvas.width - margin, canvas.height - margin)
    ImageDraw.Draw(layer).text(position, NOTICE, font=font, anchor="rb", fill=(255, 255, 255, 179),
                               stroke_width=max(1, margin // 8), stroke_fill=(35, 28, 20, 179))
    canvas.alpha_composite(layer)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_itxt("AI-Generated", "true")
    metadata.add_itxt("XML:com.adobe.xmp", XMP)
    output = BytesIO()
    canvas.save(output, "PNG", pnginfo=metadata)
    return output.getvalue()
