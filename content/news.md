---
layout: default
title: News
---

## All News

{% for item in site.data.news %}
**{{ item.date | date: "%b %e, %Y" }}** {{ item.emoji }} {{ item.text }}  
{% endfor %}
