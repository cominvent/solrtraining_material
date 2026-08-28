app_name = "solrtraining_material"
app_title = "SolrTraining Material"
app_publisher = "Cominvent AS"
app_description = "Serves solrtraining.com slide decks behind Frappe LMS access control"
app_email = "jh@cominvent.com"
app_license = "Apache-2.0"

# Frappe asks custom renderers first for every website path; ours answers only
# for /material/… (see renderer.MaterialRenderer.can_render).
page_renderer = ["solrtraining_material.renderer.MaterialRenderer"]
