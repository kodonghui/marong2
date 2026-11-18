"""TC-411. The body and outfit share one transform; exported overlap uses the approved layer order."""

from io import BytesIO

from PIL import Image, ImageDraw

from marong.pet.compose import BACKGROUNDS, Background, background_for, compose


def png(layer):
    output = BytesIO()
    layer.save(output, "PNG")
    return output.getvalue()


def block(color, region):
    image = Image.new("RGBA", (1024, 1024))
    ImageDraw.Draw(image).rectangle(region, fill=color)
    return png(image)


def verify():
    assert len(BACKGROUNDS) == 12
    assert background_for("missing").name == "home_livingroom"
    assert background_for("rainbow_meadow").name == "home_livingroom"
    assert background_for("night_blanket", memorial=True).name == "rainbow_meadow"
    assert background_for(tag="snow").name == "snow"
    fixture = Background("example", 768, 900, 400, ("home",))
    bg = png(Image.new("RGB", (1536, 1024), "white"))
    pet = block("black", (312, 300, 711, 699))
    layers = {
        "head": block("red", (400, 400, 599, 499)),
        "neck": block("green", (400, 400, 599, 599)),
        "body": block("blue", (400, 400, 599, 679)),
    }
    picture = compose(bg, fixture, pet, outfit=layers)
    with Image.open(BytesIO(picture)) as result:
        assert result.size == (1536, 1024)
        assert result.getpixel((568, 500)) == (0, 0, 0, 255)
        assert result.getpixel((967, 899)) == (0, 0, 0, 255)
        assert result.getpixel((567, 500)) == result.getpixel((967, 900)) == (255, 255, 255, 255)
        assert result.getpixel((750, 640)) == (255, 0, 0, 255)
        assert result.getpixel((750, 740)) == (0, 128, 0, 255)
        assert result.getpixel((750, 840)) == (0, 0, 255, 255)


if __name__ == "__main__":
    verify()
    print("TC-411: canvas, stage center and floor, exact per-slot overlap and fallback")
