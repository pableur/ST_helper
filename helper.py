import sublime
import sublime_plugin


def lookup_symbol(window, symbol):
    if len(symbol.strip()) < 3:
        return []

    index_locations = window.lookup_symbol_in_index(symbol)
    open_file_locations = window.lookup_symbol_in_open_files(symbol)

    def file_in_location_list(fname, locations):
        for l in locations:
            if l[0] == fname:
                return True
        return False

    # Combine the two lists, overriding results in the index with results
    # from open files, while trying to preserve the order of the files in
    # the index.
    locations = []
    ofl_ignore = []
    for l in index_locations:
        if file_in_location_list(l[0], open_file_locations):
            if not file_in_location_list(l[0], ofl_ignore):
                for ofl in open_file_locations:
                    if l[0] == ofl[0]:
                        locations.append(ofl)
                        ofl_ignore.append(ofl)
        else:
            locations.append(l)

    for ofl in open_file_locations:
        if not file_in_location_list(ofl[0], ofl_ignore):
            locations.append(ofl)

    return locations


def symbol_at_point(view, pt):
    symbol = view.substr(view.expand_by_class(pt, sublime.CLASS_WORD_START | sublime.CLASS_WORD_END, "[]{}()<>:."))
    locations = lookup_symbol(view.window(), symbol)

    if len(locations) == 0:
        symbol = view.substr(view.word(pt))
        locations = lookup_symbol(view.window(), symbol)

    return symbol, locations


def open_location(window, l):
    fname, display_fname, rowcol = l
    row, col = rowcol

    window.open_file(
        fname + ":" + str(row) + ":" + str(col),
        sublime.ENCODED_POSITION | sublime.FORCE_GROUP)


def format_location(l):
    fname, display_fname, rowcol = l
    row, col = rowcol

    return display_fname + ":" + str(row)


def location_href(l):
    return "%s:%d:%d" % (l[0], l[2][0], l[2][1])


def filter_current_symbol(view, point, symbol, locations):
    """
    Filter the point specified from the list of symbol locations. This
    results in a nicer user experience so the current symbol doesn't pop up
    when hovering over a class definition. We don't just skip all class and
    function definitions for the sake of languages that split the definition
    and implementation.
    """

    def match_view(path, view):
        fname = view.file_name()
        if fname is None:
            if path.startswith('<untitled '):
                path_view = view.window().find_open_file(path)
                return path_view and path_view.id() == view.id()
            return False
        return path == fname

    new_locations = []
    for l in locations:
        if match_view(l[0], view):
            symbol_begin_pt = view.text_point(l[2][0] - 1, l[2][1])
            symbol_end_pt = symbol_begin_pt + len(symbol)
            if point >= symbol_begin_pt and point <= symbol_end_pt:
                continue
        new_locations.append(l)
    return new_locations


def navigate_to_symbol(view, symbol, locations):
    def select_entry(window, locations, idx, orig_view, orig_sel):
        if idx >= 0:
            open_location(window, locations[idx])
        else:
            if orig_view:
                orig_view.sel().clear()
                orig_view.sel().add_all(orig_sel)
                window.focus_view(orig_view)
                orig_view.show(orig_sel[0])

    def highlight_entry(window, locations, idx):
        fname, display_fname, rowcol = locations[idx]
        row, col = rowcol

        window.open_file(
            fname + ":" + str(row) + ":" + str(col),
            group=window.active_group(),
            flags=sublime.TRANSIENT | sublime.ENCODED_POSITION | sublime.FORCE_GROUP)

    orig_sel = None
    if view:
        orig_sel = [r for r in view.sel()]

    if len(locations) == 0:
        sublime.status_message("Unable to find " + symbol)
    elif len(locations) == 1:
        open_location(view.window(), locations[0])
    else:
        window = view.window()
        window.show_quick_panel(
            items=[format_location(l) for l in locations],
            on_select=lambda x: select_entry(window, locations, x, view, orig_sel),
            on_highlight=lambda x: highlight_entry(window, locations, x),
            flags=sublime.KEEP_OPEN_ON_FOCUS_LOST)


class GotoDefinition(sublime_plugin.WindowCommand):
    def run(self, symbol=None):
        v = self.window.active_view()

        if not symbol and not v:
            return

        if not symbol:
            pt = v.sel()[0]
            symbol, locations = symbol_at_point(v, pt)
        else:
            locations = lookup_symbol(self.window, symbol)

        navigate_to_symbol(v, symbol, locations)


class ContextGotoDefinitionCommand(sublime_plugin.TextCommand):
    def run(self, edit, event):
        pt = self.view.window_to_text((event["x"], event["y"]))

        symbol, locations = symbol_at_point(self.view, pt)

        navigate_to_symbol(self.view, symbol, locations)

    def is_visible(self, event):
        pt = self.view.window_to_text((event["x"], event["y"]))
        symbol, locations = symbol_at_point(self.view, pt)

        return len(locations) > 0

    def want_event(self):
        return True


class ShowDefinitions(sublime_plugin.EventListener):
    def on_hover(self, view, point, hover_zone):
        if not view.settings().get('show_definitions'):
            return

        if hover_zone != sublime.HOVER_TEXT:
            return

        def score(scopes):
            return view.score_selector(point, scopes)

        # Limit where we show the hover popup
        if score('text.html') and not score('text.html source'):
            is_class = score('meta.attribute-with-value.class')
            is_id = score('meta.attribute-with-value.id')
            if not is_class and not is_id:
                return
        else:
            if not score('source'):
                return
            if score('comment'):
                return
            # Only show definitions in a string if there is interpolated source
            if score('string') and not score('string source'):
                return

        symbol, locations = symbol_at_point(view, point)
        locations = filter_current_symbol(view, point, symbol, locations)
        if not locations:
            return

        location_map = {location_href(l): l for l in locations}

        def on_navigate(href):
            open_location(view.window(), location_map[href])

        links = []
        for l in locations:
            links.append('<a href="%s">%s</a>' % (
                location_href(l), format_location(l)))
        links = '<br>'.join(links)
        plural = 's' if len(locations) > 1 else ''

        comment = extractInfo(view, locations)

        body = """
            <body id=show-definitions>
                <style>
                    body {
                        font-family: sans-serif;
                    }
                    h1 {
                        font-size: 1.1rem;
                        font-weight: bold;
                        margin: 0 0 0.25em 0;
                    }
                    p {
                        font-size: 1.05rem;
                        margin: 0 0 0 0;
                    }

                    ul{
                        margin: 10 0 10 0;
                    }

                </style>
                <h1>Definition%s:</h1>
                <p>%s</p>
                %s

            </body>
        """ % (plural, links, comment)

        view.show_popup(
            body,
            flags=sublime.HIDE_ON_MOUSE_MOVE_AWAY,
            location=point,
            on_navigate=on_navigate,
            max_height=2048,
            max_width=2048)

def extractInfo(view, locations):
    htmlTab=[]
    html=''

    for l in locations:
        view = view.window().find_open_file(l[0])
        #html = html+'<p>'+str(view.substr(view.line(view.text_point(l[2][0]-1,l[2][1]))))+'</p>'

    cont = True
    i=1

    while cont :        
        temp=str(view.substr(view.line(view.text_point(l[2][0]-1-i,l[2][1]))))
        pos = temp.find('#')
        
        #htmlTab.append(str(pos)+'->'+temp)
        if 'END FUNCTION' in temp:
            cont=False
        elif pos!= -1:
            i=i+1
            if '######' in temp:
                continue
            if '======' in temp:
                continue
            if '-----' in temp:
                continue
            if '<><><' in temp:
                continue
            htmlTab.append(temp[pos+1:])
        elif len(temp)==0:
            i=i+1
        elif 'FUNCTION' in temp:
            i=i+1
        #elif 'END FUNCTION' in temp:
        #    cont=False
        else :
            #htmlTab.append('->'+str(len(temp))+' -> '+temp)
            cont=False
    htmlTab.reverse()

    return html+miseEnForme(htmlTab)

#===============================================================================
# @desc    Met en forme le du javadoc
# @param   textTab : text a analyser sour forme de liste
# @return  html    : le code html a afficher
#===============================================================================
def miseEnForme(textTab):
    html=''

    inputParam  = []
    outputParam = []
    description = []
    other       = []
    last = ''

    for ligne in textTab:
        if   '@param' in ligne.lower() :
            pos = ligne.lower().find('@param')+6
            inputParam.append(ligne[pos:]) 
            last='@param'           
        elif '@return' in ligne.lower() :
            pos = ligne.lower().find('@return')+7
            outputParam.append(ligne[pos:])
            last='@return'  
        elif '@desc' in ligne.lower() :
            pos = ligne.lower().find('@desc')+5
            description.append(ligne[pos:])
            last='@desc'  
        elif '@' in ligne :
            other.append(ligne)
            last=''
        else:
            if   last == '@param' :
                lastIndex = len(inputParam)-1
                temp = "<p style='margin-left : 10px;'>"+ligne+"</p>"
                inputParam[lastIndex]=inputParam[lastIndex]+temp
            elif last == '@return':
                lastIndex = len(outputParam)-1
                temp = "<p style='margin-left : 10px;'>"+ligne+"</p>"
                outputParam[lastIndex]=outputParam[lastIndex]+temp
            elif last == '@desc'  :
                description.append(ligne)
            else:
                other.append(ligne)
                last=''  

    if len(description):
        html= html+"<p>Description</p>"
        html= html+"<ul>"
        html= html+htmlText(description)
        html= html+"</ul>"

    if len(inputParam):
        if len(inputParam)==1:
            html= html+"<p>Paramètre d'entrée :</p>"
        else:
            html= html+"<p>Paramètres d'entrées :</p>"
        html= html+htmlList(inputParam)

    if len(outputParam):
        if len(outputParam)==1:
            html= html+"<p>Paramètre de sortie :</p>"
        else:
            html= html+"<p>Paramètres de sorties :</p>"
        html= html+htmlList(outputParam)

    if len(other):
        html= html+htmlText(other)

    return html

#===============================================================================
# @desc    Convertit une liste python en liste a puce HTML
# @param   liste   : Liste a transformer
# @return  html    : liste sour forme de code html
#===============================================================================
def htmlList(liste):
    html='<ul>'
    for ligne in liste:
        html= html+"<li>"+ligne+"</li>"
    html=html+'</ul>'

    return html

#===============================================================================
# @desc    Convertit une liste python en paragraphe HTML
# @param   liste   : Liste a transformer
# @return  html    : paragraphe sour forme de code html
#===============================================================================
def htmlText(liste):
    html = ''
    for ligne in liste:
        html= html+"<p>"+ligne+"</p>"
    return html
