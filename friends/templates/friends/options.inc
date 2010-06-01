<ul id="contacts-sidebar" class="tabbed-bar">
	{% url edit_friends as edit_friends_url %}{% ifequal request.path edit_friends_url %}<li class="active" id="general">Edit Contacts</li>{% else %}<li id="general"><a href="{{ edit_friends_url }}">Edit Contacts</a></li>{% endifequal %}
	{% url import_file_contacts as import_file_contacts_url %}{% ifequal request.path import_file_contacts_url %}<li class="active" id="presence">Import E-mail Contacts</li>{% else %}<li id="presence"><a href="{{ import_file_contacts_url }}">Import E-mail Contacts</a></li>{% endifequal %}
	{% url import_google_contacts as import_google_contacts_url %}{% ifequal request.path import_google_contacts_url %}<li class="active" id="interests">Import Google Contacts</li>{% else %}<li id="interests"><a href="{{ import_google_contacts_url }}">Import Google Contacts</a></li>{% endifequal %}
	{% url requests_received as requests_received_url %}{% ifequal request.path requests_received_url %}<li class="active" id="affiliations">Invitations Sent</li>{% else %}<li id="affiliations"><a href="{{ requests_received_url }}">Invitations Sent</a></li>{% endifequal %}
	{% url requests_received as requests_received_url %}{% ifequal request.path requests_received_url %}<li class="active" id="affiliations">Requests Received</li>{% else %}<li id="affiliations"><a href="{{ requests_received_url }}">Requests Received</a></li>{% endifequal %}
</ul>