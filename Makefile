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

# Uses the container's own settings, so a non-default DB_USER/DB_NAME in .env works too.
psql:
	docker compose exec db sh -c 'exec psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'
