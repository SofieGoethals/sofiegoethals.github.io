---
layout: default
title: News
---

## All news

{% for item in site.data.news %}
**{{ item.date | date: "%b %e, %Y" }}** {{ item.emoji }} {{ item.text }}  
{% endfor %}
