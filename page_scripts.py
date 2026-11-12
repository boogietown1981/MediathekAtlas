"""Puts the page's own scripts into the page (0.5.74); the list of scripts is server.SCRIPTS."""
import re

def inline_scripts(html,folder,scripts):
    """0.5.74: the page carries its own scripts instead of fetching some twenty files.

    Björn (12.11.2026, Chrome): single scripts did not arrive (first player.js, then netzkino_detail.js), so
    buttons failed. With the scripts inside the page nothing can go missing: either the page arrives or not.
    Each file stays its own <script> (same order, an error in one does not stop the others) and keeps its
    name in error messages through sourceURL. A file that cannot be read keeps its ordinary tag.
    """
    def one(match):
        name=match.group(1)
        if '/'+name not in scripts:return match.group(0)
        try:code=(folder/name).read_text(encoding='utf-8')
        except (OSError,UnicodeDecodeError):return match.group(0)
        return '<script data-file="%s">%s\n//# sourceURL=/%s\n</script>'%(name,code.replace('</script','<\\/script'),name)
    return re.sub(r'<script src="/([a-z_]+\.js)"></script>',one,html)
