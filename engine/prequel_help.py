"""Update resource text with launcher and same-window campaign instructions."""
import hashlib
from resource_codec import entries, parts, compound, replace, archive


def patch(raw, expected_sha256):
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Unexpected Prequel help resource')
    rows = entries(raw)
    text = parts(rows[456][1])
    if len(text) != 10:
        raise ValueError('Unexpected Prequel help pages')
    text[1] = (
        b'SAVING YOUR MISSION\n\nPress P to pause during a mission. In the native launcher, '
        b'enter a name and choose Save paused game. These exact snapshots preserve the fight, '
        b'not just the mission selection.\n\nExit the current game before choosing Load selected '
        b'state. The saved mission reopens paused. Retail and Prequel saves are listed separately.\0'
    )
    text[2] = (
        b'CONTINUING THE STORY\n\nAfter completing Operation Citadel, choose Main Menu '
        b'on the Prequel mission screen to return to Terra Nova: Strike Force Centauri. '
        b'The campaign changes in the same window.\n\nYour retail campaign progress is kept '
        b'separate. Options are shared between both campaigns.\0'
    )
    replace(rows, 456, compound(text))
    return archive(rows)
