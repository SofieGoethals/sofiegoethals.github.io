---
layout: default
title: News
---

## All news

{% for item in site.data.news %}
**{{ item.date }}** {{ item.emoji }} {{ item.text | markdownify | remove: '<p>' | remove: '</p>' | strip }}

{% endfor %}
