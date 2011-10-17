<ul class="shared-friends">
{% for sf in shared_friends %}
	<li>{{ sf.get_full_name|default:sf }}</li>
{% endfor %}
</ul>