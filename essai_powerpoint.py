"""Essai : piloter un PowerPoint deja ouvert depuis Python (Windows, pywin32).

    python essai_powerpoint.py          # mode interactif
    python essai_powerpoint.py --auto   # auto-test (ouvre une presentation jetable)

Touches (mode interactif) :
    n / fleche droite  diapo suivante      p / fleche gauche  diapo precedente
    g                  aller a la diapo N  s                  lancer le diaporama
    x                  quitter le diapo    q                  quitter l'essai

Les changements de diapo (y compris faits a la main dans PowerPoint) sont
detectes par sondage toutes les 200 ms, avec le texte des notes : c'est la
que l'on pourrait mettre un tag de declenchement lumiere, ex. [MEM 3].
"""

import re
import sys
import time

import pythoncom
import pywintypes
import win32com.client

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PP_SLIDESHOW_DONE = 5
CUE_RE = re.compile(r"\[(MEM|SEQ|FX)\s*(\d+)\]", re.IGNORECASE)


def get_app():
    """Instance PowerPoint en cours, ou None (ne lance jamais PowerPoint)."""
    try:
        return win32com.client.GetActiveObject("PowerPoint.Application")
    except pywintypes.com_error:
        return None


def get_view(app):
    """Vue du diaporama en cours, ou None."""
    try:
        if app.SlideShowWindows.Count == 0:
            return None
        view = app.SlideShowWindows(1).View
        return None if view.State == PP_SLIDESHOW_DONE else view
    except pywintypes.com_error:
        return None


def slide_notes(slide):
    try:
        return slide.NotesPage.Shapes.Placeholders(2).TextFrame.TextRange.Text.strip()
    except pywintypes.com_error:
        return ""


def slide_title(slide):
    try:
        if slide.Shapes.HasTitle:
            return slide.Shapes.Title.TextFrame.TextRange.Text.strip()
    except pywintypes.com_error:
        pass
    return ""


def current_slide(view):
    """(index, total, titre, notes) ou None (ecran noir de fin, transition...)."""
    try:
        slide = view.Slide
        total = view.Parent.Presentation.Slides.Count
        return slide.SlideIndex, total, slide_title(slide), slide_notes(slide)
    except pywintypes.com_error:
        return None


def describe(info):
    idx, total, title, notes = info
    line = f"Diapo {idx}/{total}"
    if title:
        line += f"  « {title} »"
    cues = CUE_RE.findall(notes)
    if cues:
        line += "  -> declencheurs : " + ", ".join(f"{k.upper()} {n}" for k, n in cues)
    elif notes:
        line += f"  (notes : {notes[:60]})"
    return line


def interactive():
    import msvcrt

    app = get_app()
    if app is None:
        print("PowerPoint n'est pas lance. Ouvre une presentation puis relance l'essai.")
        return
    print(f"PowerPoint trouve : {app.Presentations.Count} presentation(s) ouverte(s)")
    for i in range(1, app.Presentations.Count + 1):
        pres = app.Presentations(i)
        print(f"  {i}. {pres.Name} ({pres.Slides.Count} diapos)")
    print(__doc__.split("Touches")[1].split("Les changements")[0])

    last = object()
    while True:
        view = get_view(app)
        info = current_slide(view) if view else None
        state = info[:1] if info else ("diapo" if view else "arret")
        if state != last:
            last = state
            if info:
                print(describe(info))
            elif view:
                print("Diaporama : ecran de fin / noir")
            else:
                print("Pas de diaporama en cours (touche s pour le lancer)")

        if msvcrt.kbhit():
            key = msvcrt.getwch()
            if key in ("\x00", "\xe0"):  # touche etendue (fleches)
                key = {"M": "n", "K": "p"}.get(msvcrt.getwch(), "")
            key = key.lower()
            try:
                if key == "q":
                    break
                elif key == "s":
                    if app.Presentations.Count:
                        app.Presentations(1).SlideShowSettings.Run()
                    else:
                        print("Aucune presentation ouverte")
                elif view is None and key in "npgx":
                    print("Pas de diaporama en cours")
                elif key == "n":
                    view.Next()
                elif key == "p":
                    view.Previous()
                elif key == "x":
                    view.Exit()
                elif key == "g":
                    n = input("Aller a la diapo : ").strip()
                    if n.isdigit():
                        view.GotoSlide(int(n))
            except pywintypes.com_error as e:
                print(f"Erreur PowerPoint : {e.excepinfo[2] if e.excepinfo else e}")
        time.sleep(0.2)


def auto_test():
    """Cree une presentation jetable de 3 diapos, la pilote, puis ferme tout."""
    already_running = get_app() is not None
    app = win32com.client.Dispatch("PowerPoint.Application")
    pres = app.Presentations.Add(WithWindow=True)
    try:
        for i in range(1, 4):
            slide = pres.Slides.Add(i, 2)  # ppLayoutText
            slide.Shapes.Title.TextFrame.TextRange.Text = f"Titre {i}"
            slide.NotesPage.Shapes.Placeholders(2).TextFrame.TextRange.Text = f"Intro [MEM {i}]"
        pres.SlideShowSettings.Run()
        time.sleep(1.0)
        view = get_view(app)
        assert view is not None, "diaporama non detecte"
        print(describe(current_slide(view)))
        view.Next(); time.sleep(0.5)
        print(describe(current_slide(view)))
        view.GotoSlide(3); time.sleep(0.5)
        info = current_slide(view)
        print(describe(info))
        assert info[0] == 3, f"GotoSlide(3) -> diapo {info[0]}"
        view.Previous(); time.sleep(0.5)
        assert current_slide(view)[0] == 2
        view.Exit()
        print("AUTO-TEST OK")
    finally:
        pres.Saved = True
        pres.Close()
        if not already_running:
            app.Quit()


if __name__ == "__main__":
    pythoncom.CoInitialize()
    if "--auto" in sys.argv:
        auto_test()
    else:
        interactive()
