test:
	python manage.py test --settings=root.settings_test

mig:
	python manage.py makemigrations
	python manage.py migrate

run:
	python manage.py runserver

up:
	docker compose up -d

down:
	docker compose down

psql:
	docker compose exec db psql -U onlinechat_user -d onlinechat
