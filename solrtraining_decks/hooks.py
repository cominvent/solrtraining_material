app_name = "solrtraining_decks"
app_title = "SolrTraining Decks"
app_publisher = "Cominvent AS"
app_description = "Serves solrtraining.com slide decks behind Frappe LMS access control"
app_email = "jh@cominvent.com"
app_license = "MIT"

# Frappe asks custom renderers first for every website path; ours answers only
# for /decks/… (see renderer.DeckRenderer.can_render).
page_renderer = ["solrtraining_decks.renderer.DeckRenderer"]
