"""Frames are PNG bytes in theme colours. Phantom nodes read as hollow."""
import io

from PIL import Image

from griot import theme
from griot.brain import graph as g
from griot.brain.pulse import WRITE, Pulses
from griot.brain.render import blend, frame
from griot.brain.sim import Sim

SIZE = (200, 120)


def two_nodes(phantom_second: bool) -> g.Graph:
    return g.Graph(names=["A", "B"], paths=["/tmp/A.md", None if phantom_second else "/tmp/B.md"],
                   edges=[(0, 1)], degree=[1, 1], by_path={"/tmp/A.md": 0},
                   adjacency=[[1], [0]], fingerprint="test")


def render(graph, pulses=None):
    sim = Sim(graph, SIZE, seed=2)
    return frame(graph, sim, pulses or Pulses(graph), theme.PALETTE, SIZE)


def test_a_frame_is_a_png_of_the_requested_size():
    data = render(two_nodes(False))
    img = Image.open(io.BytesIO(data))
    assert img.format == "PNG"
    assert img.size == SIZE


def test_frames_are_not_blank():
    img = Image.open(io.BytesIO(render(two_nodes(False)))).convert("RGB")
    assert len(img.getcolors(maxcolors=100000)) > 1, "something was drawn"


def test_a_pulse_changes_the_frame():
    graph = two_nodes(False)
    quiet = render(graph)
    pulses = Pulses(graph)
    pulses.hit(0, WRITE)
    assert render(graph, pulses) != quiet


def test_phantom_nodes_render_differently_from_real_ones():
    assert render(two_nodes(True)) != render(two_nodes(False))


def test_no_hex_literals_in_the_module():
    """Colours come from theme tokens; the module must not carry its own."""
    import re
    from pathlib import Path
    source = (Path(__file__).parents[1] / "src/griot/brain/render.py").read_text()
    assert not re.search(r"#[0-9A-Fa-f]{6}", source)


def test_blend_interpolates_between_two_tokens():
    assert blend("#000000", "#FFFFFF", 0.0) == (0, 0, 0)
    assert blend("#000000", "#FFFFFF", 1.0) == (255, 255, 255)
    assert blend("#000000", "#FFFFFF", 0.5) == (127, 127, 127)


def test_a_pulse_blooms_the_node_itself():
    """The electron path alone changes the frame bytes, so a byte-level
    comparison cannot see whether node bloom works. Sample the node."""
    graph = two_nodes(False)
    sim = Sim(graph, SIZE, seed=2)
    x, y = sim.pos[0]

    def node_pixels(pulses):
        img = Image.open(io.BytesIO(
            frame(graph, sim, pulses, theme.PALETTE, SIZE))).convert("RGB")
        box = img.crop((max(0, int(x) - 6), max(0, int(y) - 6),
                        min(SIZE[0], int(x) + 7), min(SIZE[1], int(y) + 7)))
        return sum(sum(px) for px in box.getdata())

    quiet = Pulses(graph)
    hot = Pulses(graph)
    hot.hit(0, WRITE)
    assert node_pixels(hot) > node_pixels(quiet), \
        "a written node must grow and brighten where it sits"
