set -e
            echo "==> Navigating to project directory..."
            cd ~/apps/spoken-api

            echo "==> Running Alembic migrations..."
            # Use -T for non-interactive shell in CI
            docker compose -f docker-compose.prod.yml exec -T api \
              alembic -x sqlalchemy.url="${DATABASE_URL_DIRECT}" upgrade head
            echo "==> Migrations complete."