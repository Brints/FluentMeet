set -e

            echo "==> Navigating to project directory..."
            cd ~/apps/spoken-api

            echo "==> Pulling latest code from main..."
            git pull origin main

            echo "==> Rebuilding API container..."
            docker compose -f docker-compose.prod.yml build api

            echo "==> Restarting API container..."
            docker compose -f docker-compose.prod.yml up -d api

            echo "==> Waiting for container to be healthy (up to 90s)..."
            ITER=0
            while [ $ITER -lt 12 ]; do
              STATUS=$(docker inspect --format='{{.State.Health.Status}}' spoken-api 2>/dev/null || echo "starting")
              echo "==> Current status: $STATUS"
              if [ "$STATUS" = "healthy" ]; then
                break
              fi
              sleep 5
              ITER=$((ITER + 1))
            done

            STATUS=$(docker inspect --format='{{.State.Health.Status}}' spoken-api 2>/dev/null || echo "unknown")
            echo "==> Container health status: $STATUS"
            if [ "$STATUS" != "healthy" ]; then
              echo "ERROR: Container did not become healthy in time!"
              docker compose -f docker-compose.prod.yml logs --tail=50 api
              exit 1
            fi