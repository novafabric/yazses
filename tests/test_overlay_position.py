from yazses.overlay.position import place_fixed, place_near_cursor

SCREEN = (0, 0, 1920, 1080)
SIZE = 200
OFFSET = 28


def test_near_cursor_default_below_right():
    x, y = place_near_cursor((500, 400), SIZE, SCREEN, OFFSET)
    assert x == 528
    assert y == 428


def test_near_cursor_flips_at_right_edge():
    x, _ = place_near_cursor((1900, 400), SIZE, SCREEN, OFFSET)
    # Would overflow right → placed to the left of the cursor, fully on-screen.
    assert x + SIZE <= 1920
    assert x < 1900


def test_near_cursor_flips_at_bottom_edge():
    _, y = place_near_cursor((500, 1070), SIZE, SCREEN, OFFSET)
    assert y + SIZE <= 1080
    assert y < 1070


def test_near_cursor_clamped_into_screen():
    # Cursor in the extreme corner: result must stay within bounds.
    x, y = place_near_cursor((1919, 1079), SIZE, SCREEN, OFFSET)
    assert 0 <= x <= 1920 - SIZE
    assert 0 <= y <= 1080 - SIZE


def test_near_cursor_respects_screen_origin_offset():
    screen = (1920, 0, 1920, 1080)  # second monitor to the right
    x, y = place_near_cursor((2400, 300), SIZE, screen, OFFSET)
    assert x >= 1920
    assert x + SIZE <= 1920 + 1920


def test_place_fixed_positions():
    top = place_fixed("top_center", SIZE, SCREEN)
    bottom = place_fixed("bottom_center", SIZE, SCREEN)
    corner = place_fixed("corner", SIZE, SCREEN)
    assert top[0] == bottom[0] == (1920 - SIZE) // 2
    assert top[1] < bottom[1]
    assert corner[0] > top[0]


def test_place_fixed_unknown_falls_back_to_bottom_center():
    assert place_fixed("nonsense", SIZE, SCREEN) == place_fixed("bottom_center", SIZE, SCREEN)
