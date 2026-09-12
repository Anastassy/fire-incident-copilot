# Исходник слайдов Firewatch S6

`build.mjs` создаёт 11 редактируемых слайдов PowerPoint и PNG 1920×1080 по
`dashboard/VIDEO_SCRIPT.md`, редакция S6. Нижние 180 пикселей оставлены для
субтитров фильма. Текст и схемы остаются нативными объектами слайдов.

Нужны Node.js, bundled `@oai/artifact-tool`, Python и пакет навыка Presentations
из Codex. Получите актуальные пути через `load_workspace_dependencies` и каталог
навыков. Скрипт не устанавливает пакеты и не требует LibreOffice.

Задайте абсолютные пути для своей машины:

```sh
export RUNTIME_NODE="/absolute/path/to/node/bin/node"
export RUNTIME_NODE_MODULES="/absolute/path/to/node/node_modules"
export RUNTIME_PYTHON="/absolute/path/to/python/bin/python3"
export PRESENTATIONS_SKILL_DIR="/absolute/path/to/skills/presentations"
export FIREWATCH_OUTPUT_DIR="/absolute/path/outside/repository/firewatch-slides"
"$RUNTIME_NODE" dashboard/video/s6/slides/build.mjs v4
```

Результаты в `FIREWATCH_OUTPUT_DIR/slides/`: `Firewatch-120s-S6-v4.pptx`,
11 PNG (`B01`–`B05`, `T01`–`T03`, `F01`–`F03`) и `slides.json` с монтажными
интервалами. Проверки пакета и геометрии, а также черновик лежат в `.build/`.
Новый суффикс сохраняет предыдущий PPTX, но PNG обновляются. Для независимых
редакций используйте разные выходные каталоги. Не добавляйте результаты в Git.

Исходная версия v3 проверена через Artifact Tool: 11 кадров, читаемость,
геометрия, источники и направления связей. При смене машины проверьте выбранный
шрифт и все PNG повторно. В PowerPoint отдельная визуальная проверка не проводилась.
Источник CSB, ограничения демонстрации и статус цели пилота сохранены в слайдах.
