pipeline {
    agent any

    options {
        timestamps()
        ansiColor('xterm')
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '10', artifactNumToKeepStr: '10'))
        timeout(time: 30, unit: 'MINUTES')
        skipDefaultCheckout(true)
    }

    environment {
        APP_SERVICE          = 'auth_app'
        CI                   = 'true'
        REPORTS_DIR          = 'reports'
        COMPOSE_PROJECT_NAME = "auth_ci_${env.BUILD_NUMBER}"
        TEST_DATABASE_URL    = 'postgresql+asyncpg://postgres:postgres@shared_test_db:5432/trading_test_db'
        DATABASE_URL         = 'postgresql+asyncpg://postgres:postgres@shared_test_db:5432/trading_test_db'
        SECRET_KEY           = 'ci-dummy-secret-key-32-characters-minimum'
        RESEND_API_KEY       = 're_dummy_resend_api_key_for_ci_testing_purposes'
        EMAIL_FROM           = 'noreply@example.com'
        FRONTEND_URL         = 'http://localhost:3000'
        PROD_IMAGE_TAG       = "authentication-service:ci-${env.BUILD_NUMBER}"
    }

    stages {
        stage('Checkout') {
            steps {
                script {
                    echo '=== STAGE: Checkout ==='
                    echo 'Checking out code from version control...'
                }
                checkout scm
                script {
                    echo 'Checking out shared infrastructure repository...'
                    checkout([
                        $class: 'GitSCM',
                        branches: [[name: '*/main']],
                        extensions: [[$class: 'RelativeTargetDirectory', relativeTargetDir: 'infrastructure']],
                        userRemoteConfigs: [[
                            url: 'https://github.com/TradeDisciplineAI/infrastructure.git',
                            credentialsId: 'github-pat'
                        ]]
                    ])
                }
            }
        }

        stage('Show Build Metadata') {
            steps {
                script {
                    echo '=== STAGE: Show Build Metadata ==='
                    echo "Build Number:  ${env.BUILD_NUMBER}"
                    echo "Build URL:     ${env.BUILD_URL}"
                    echo "Branch:        ${env.BRANCH_NAME ?: 'unknown'}"
                    echo "Commit:        ${env.GIT_COMMIT ?: 'unknown'}"
                    echo "Jenkins Node:  ${env.NODE_NAME ?: 'Built-in'}"
                    echo "Workspace:     ${env.WORKSPACE}"
                }
                echo 'Build Timestamp:'
                sh 'date'
            }
        }

        stage('Prepare Workspace') {
            steps {
                script {
                    echo '=== STAGE: Prepare Workspace ==='
                    echo "Creating clean report directories under ${env.REPORTS_DIR}..."
                    sh "mkdir -p ${env.REPORTS_DIR}/junit"
                    sh "mkdir -p ${env.REPORTS_DIR}/coverage"
                    sh "mkdir -p ${env.REPORTS_DIR}/htmlcov"
                    echo 'Workspace preparation succeeded.'
                }
            }
        }

        stage('Validate Build Environment') {
            steps {
                script {
                    echo '=== STAGE: Validate Build Environment ==='
                    echo 'Validating host tooling availability...'
                }
                echo 'Checking Git version...'
                sh 'git --version'
                echo 'Checking Docker version...'
                sh 'docker --version'
                echo 'Checking Docker Compose version...'
                sh 'docker compose version'
                script {
                    echo 'Build environment validation succeeded.'
                }
            }
        }

        stage('Build Authentication Container') {
            steps {
                script {
                    echo '=== STAGE: Build Authentication Container ==='
                    echo "Building container for service: ${env.APP_SERVICE}"
                    echo "Executing: docker compose build ${env.APP_SERVICE}"
                }
                sh "docker compose build ${env.APP_SERVICE}"
                script {
                    echo "Container for ${env.APP_SERVICE} built successfully."
                }
            }
        }

        stage('Verify Container Environment') {
            steps {
                script {
                    echo '=== STAGE: Verify Container Environment ==='
                    echo "Verifying environment inside container: ${env.APP_SERVICE}"
                    echo "Executing checks via: docker compose run --rm ${env.APP_SERVICE}"
                }
                sh "docker compose run --rm ${env.APP_SERVICE} sh -c 'python3 --version && uv --version'"
                script {
                    echo 'Container environment verification succeeded.'
                }
            }
        }

        stage('Ruff Format Check') {
            steps {
                script {
                    echo '=== STAGE: Ruff Format Check ==='
                    echo 'Verifying code formatting layout...'
                    echo 'Executing: ruff format --check'
                }
                sh "docker compose -f docker-compose.yml run --rm ${env.APP_SERVICE} uv run ruff format --check src tests"
                script {
                    echo 'Code formatting validation succeeded.'
                }
            }
        }

        stage('Ruff Lint') {
            steps {
                script {
                    echo '=== STAGE: Ruff Lint ==='
                    echo 'Running linter, import sorter, and security checks...'
                    echo 'Executing: ruff check (generating ruff-log.txt in pylint format)'
                    try {
                        sh "docker compose -f docker-compose.yml run --name auth_ruff_${env.BUILD_NUMBER} ${env.APP_SERVICE} uv run ruff check --output-format=pylint --output-file=${env.REPORTS_DIR}/ruff-log.txt src tests"
                    } finally {
                        sh "docker cp auth_ruff_${env.BUILD_NUMBER}:/app/${env.REPORTS_DIR}/ruff-log.txt ${env.WORKSPACE}/${env.REPORTS_DIR}/ruff-log.txt || true"
                        sh "docker rm -f auth_ruff_${env.BUILD_NUMBER} || true"
                    }
                    echo 'Ruff linting checks completed successfully.'
                }
            }
        }

        stage('MyPy Type Check') {
            steps {
                script {
                    echo '=== STAGE: MyPy Type Check ==='
                    echo 'Executing strict type check checks...'
                    echo 'Executing: mypy src (generating mypy-log.txt)'
                    try {
                        sh "docker compose -f docker-compose.yml run --name auth_mypy_${env.BUILD_NUMBER} ${env.APP_SERVICE} bash -c 'set -o pipefail && uv run mypy src | tee ${env.REPORTS_DIR}/mypy-log.txt'"
                    } finally {
                        sh "docker cp auth_mypy_${env.BUILD_NUMBER}:/app/${env.REPORTS_DIR}/mypy-log.txt ${env.WORKSPACE}/${env.REPORTS_DIR}/mypy-log.txt || true"
                        sh "docker rm -f auth_mypy_${env.BUILD_NUMBER} || true"
                    }
                    echo 'MyPy type checking checks completed successfully.'
                }
            }
        }

        stage('Semgrep Security Scan') {
            steps {
                script {
                    echo '=== STAGE: Semgrep Security Scan ==='
                    echo 'Starting security scan...'
                    echo 'Checking Semgrep version...'
                    sh "docker compose -f docker-compose.yml run --rm ${env.APP_SERVICE} uv run semgrep --version"
                    echo 'Configuration: --config=auto'
                    echo 'Output Format: SARIF'
                    echo "Report Location: ${env.REPORTS_DIR}/semgrep.sarif"
                    try {
                        sh "docker compose -f docker-compose.yml run --name auth_semgrep_${env.BUILD_NUMBER} ${env.APP_SERVICE} uv run semgrep --config=auto --sarif --output=${env.REPORTS_DIR}/semgrep.sarif || true"
                    } finally {
                        sh "docker cp auth_semgrep_${env.BUILD_NUMBER}:/app/${env.REPORTS_DIR}/semgrep.sarif ${env.WORKSPACE}/${env.REPORTS_DIR}/semgrep.sarif || true"
                        sh "docker rm -f auth_semgrep_${env.BUILD_NUMBER} || true"
                    }
                    echo 'Semgrep security scan completed.'
                }
            }
        }

        stage('Ensure Test Infrastructure') {
            steps {
                script {
                    echo '=== STAGE: Ensure Test Infrastructure ==='

                    // Check if shared_test_db is running (exits 0 if running)
                    boolean dbRunning = sh(
                        script: "docker ps -q -f name=shared_test_db -f status=running | grep .",
                        returnStatus: true
                    ) == 0

                    // Check if shared_redis is running (exits 0 if running)
                    boolean redisRunning = sh(
                        script: "docker ps -q -f name=shared_redis -f status=running | grep .",
                        returnStatus: true
                    ) == 0

                    if (dbRunning && redisRunning) {
                        echo "Both shared_test_db and shared_redis are already running. Reusing existing containers."
                    } else {
                        String startServices = ""
                        if (!dbRunning) {
                            echo "shared_test_db is not running. Will start test_db service..."
                            startServices += " test_db"
                        } else {
                            echo "shared_test_db is already running. Reusing it."
                        }
                        if (!redisRunning) {
                            echo "shared_redis is not running. Will start redis service..."
                            startServices += " redis"
                        } else {
                            echo "shared_redis is already running. Reusing it."
                        }

                        echo "Executing: docker compose -f infrastructure/docker-compose.yml -p trading_infra up -d${startServices}"
                        int buildStatus = sh(
                            script: "docker compose -f infrastructure/docker-compose.yml -p trading_infra up -d${startServices}",
                            returnStatus: true
                        )
                        if (buildStatus != 0) {
                            echo "FAIL: Failed to start infrastructure containers."
                            sh "docker compose -f infrastructure/docker-compose.yml -p trading_infra ps"
                            sh "docker compose -f infrastructure/docker-compose.yml -p trading_infra logs"
                            error "Infrastructure startup failed."
                        }
                    }
                    echo 'Infrastructure start checks completed.'
                }
            }
        }

        stage('Database Health Check') {
            steps {
                script {
                    echo '=== STAGE: Database Health Check ==='
                    echo 'Checking database container availability...'

                    int attempts = 12
                    int delaySeconds = 5
                    boolean dbReady = false

                    for (int i = 1; i <= attempts; i++) {
                        echo "Attempt ${i} of ${attempts}: Checking database connection via pg_isready..."
                        int status = sh(
                            script: "docker exec shared_test_db pg_isready -U postgres",
                            returnStatus: true
                        )
                        if (status == 0) {
                            echo "Database is ready to accept connections."
                            dbReady = true
                            break
                        }
                        echo "Database not ready yet. Sleeping for ${delaySeconds} seconds..."
                        sleep(delaySeconds)
                    }

                    if (!dbReady) {
                        echo "FAIL: Database did not become healthy. Printing logs..."
                        sh "docker logs shared_test_db"
                        error "FAIL: Database did not become healthy within 60 seconds."
                    }
                }
            }
        }
        stage('Validate Environment Variables') {
            steps {
                script {
                    echo '=== STAGE: Validate Environment Variables ==='
                    def requiredVars = ['SECRET_KEY', 'DATABASE_URL', 'RESEND_API_KEY', 'EMAIL_FROM', 'FRONTEND_URL']
                    def missingVars = []
                    for (varName in requiredVars) {
                        def val = env."${varName}"
                        if (val == null || val.trim() == "") {
                            missingVars.add(varName)
                        }
                    }
                    if (missingVars.size() > 0) {
                        error "FAIL: Missing required environment variables: ${missingVars.join(', ')}"
                    }

                    // Validate SECRET_KEY length
                    if (env.SECRET_KEY.length() < 32) {
                        error "FAIL: SECRET_KEY must be at least 32 characters (current length: ${env.SECRET_KEY.length()})"
                    }

                    echo 'All required environment variables validated successfully.'
                }
            }
        }

        stage('Database Migration Validation') {
            steps {
                script {
                    echo '=== STAGE: Database Migration Validation ==='
                    echo 'Running Alembic upgrade head checks...'
                    echo 'Executing: alembic upgrade head'
                }
                sh "docker compose -f docker-compose.yml run --rm -e DATABASE_URL=${env.TEST_DATABASE_URL} ${env.APP_SERVICE} uv run alembic upgrade head"
                script {
                    echo 'Database migration validation completed successfully.'
                }
            }
        }

        stage('Execute Pytest Suite') {
            steps {
                script {
                    echo '=== STAGE: Execute Pytest Suite ==='
                    echo 'Running pytest test cases and generating coverage...'
                    try {
                        sh "docker compose -f docker-compose.yml run --name auth_pytest_${env.BUILD_NUMBER} -e TEST_DATABASE_URL=${env.TEST_DATABASE_URL} -e DATABASE_URL=${env.TEST_DATABASE_URL} ${env.APP_SERVICE} uv run pytest --junitxml=${env.REPORTS_DIR}/junit.xml --cov-report=xml:${env.REPORTS_DIR}/coverage.xml --cov-report=html:${env.REPORTS_DIR}/htmlcov"
                    } finally {
                        sh """
                            mkdir -p "${env.WORKSPACE}/${env.REPORTS_DIR}"
                            docker cp "auth_pytest_${env.BUILD_NUMBER}:/app/${env.REPORTS_DIR}/." "${env.WORKSPACE}/${env.REPORTS_DIR}/"
                        """
                        sh "docker rm -f auth_pytest_${env.BUILD_NUMBER} || true"
                    }
                    echo 'Pytest suite executed successfully.'
                }
            }
        }

        stage('Production Docker Image Validation') {
            steps {
                script {
                    echo '=== STAGE: Production Docker Image Validation ==='
                    echo 'Building production Docker image...'
                }
                sh "docker build -t ${env.PROD_IMAGE_TAG} ."
                script {
                    echo 'Production Docker image built successfully.'
                    echo 'Starting metadata inspection...'
                }
                sh """
                    echo "Image Tag:   ${env.PROD_IMAGE_TAG}"
                    echo -n "Image ID:    " && docker inspect --format='{{.Id}}' ${env.PROD_IMAGE_TAG}
                    echo -n "Image Size:  " && docker inspect --format='{{.Size}} bytes' ${env.PROD_IMAGE_TAG}
                    echo -n "Created At:  " && docker inspect --format='{{.Created}}' ${env.PROD_IMAGE_TAG}
                    echo -n "Entrypoint:  " && docker inspect --format='{{json .Config.Entrypoint}}' ${env.PROD_IMAGE_TAG}
                    echo -n "CMD:         " && docker inspect --format='{{json .Config.Cmd}}' ${env.PROD_IMAGE_TAG}
                """
                script {
                    echo 'Starting runtime user security validation...'
                }
                sh """
                    image_user=\$(docker inspect --format='{{.Config.User}}' ${env.PROD_IMAGE_TAG})
                    echo "Configured runtime user: '\$image_user'"
                    if [ -z "\$image_user" ] || [ "\$image_user" = "root" ] || [ "\$image_user" = "0" ]; then
                        echo "FAIL: Runtime user security violation: Image is configured to run as root!"
                        exit 1
                    fi
                    echo "Runtime user validation succeeded."
                """
                script {
                    echo 'Starting developer tooling presence validation...'
                }
                sh """
                    for tool in pytest ruff mypy locust semgrep pre-commit; do
                        echo "Verifying absence of dev tool: \$tool"
                        if docker run --rm --entrypoint="" ${env.PROD_IMAGE_TAG} sh -c "command -v \$tool" >/dev/null 2>&1; then
                            echo "FAIL: Production image security violation: developer tool '\$tool' was found!"
                            exit 1
                        else
                            echo "Pass: '\$tool' is not installed."
                        fi
                    done
                    echo "Developer tooling absence validation succeeded."
                """
                script {
                    echo 'Starting OCI label configuration inspection...'
                }
                sh """
                    labels=\$(docker inspect --format='{{json .Config.Labels}}' ${env.PROD_IMAGE_TAG})
                    if [ "\$labels" = "null" ] || [ "\$labels" = "{}" ]; then
                        echo "OCI Labels: None configured."
                    else
                        echo "OCI Labels: \$labels"
                    fi
                """
                script {
                    echo 'Production image validation completed successfully.'
                }
            }
        }
        stage('Validate Reports Presence') {
            steps {
                script {
                    echo '=== STAGE: Validate Reports Presence ==='
                    sh "find ${env.REPORTS_DIR} -type f || true"
                    sh "ls -R ${env.REPORTS_DIR} || true"
                }
            }
        }
    }

    post {
        always {
            script {
                echo '=== POST ACTIONS ==='

                // Clean up the temporary production validation image if it was built
                if (sh(script: "docker image inspect ${env.PROD_IMAGE_TAG} >/dev/null 2>&1", returnStatus: true) == 0) {
                    echo "Removing temporary production image: ${env.PROD_IMAGE_TAG}"
                    sh "docker rmi -f ${env.PROD_IMAGE_TAG} || true"
                }

                // Tear down compose projects to delete containers, networks, and volumes
                echo "Tearing down application compose project: ${env.COMPOSE_PROJECT_NAME}..."
                sh "docker compose -f docker-compose.yml -p ${env.COMPOSE_PROJECT_NAME} down -v || true"

                // Keep the shared infrastructure running across builds to prevent resource recreation
                echo "Shared infrastructure project 'trading_infra' remains running."

                echo 'Publishing static analysis warnings reports...'

                if (fileExists("${env.REPORTS_DIR}/ruff-log.txt")) {
                    recordIssues(
                        enabledForFailure: true,
                        tools: [pyLint(pattern: "${env.REPORTS_DIR}/ruff-log.txt", id: 'ruff', name: 'Ruff Lint')]
                    )
                } else {
                    echo "WARNING: Ruff lint report is missing!"
                    currentBuild.result = 'UNSTABLE'
                }

                if (fileExists("${env.REPORTS_DIR}/mypy-log.txt")) {
                    recordIssues(
                        enabledForFailure: true,
                        tools: [myPy(pattern: "${env.REPORTS_DIR}/mypy-log.txt", id: 'mypy', name: 'MyPy Type Check')]
                    )
                } else {
                    echo "WARNING: MyPy log report is missing!"
                    currentBuild.result = 'UNSTABLE'
                }

                if (fileExists("${env.REPORTS_DIR}/semgrep.sarif")) {
                    recordIssues(
                        enabledForFailure: true,
                        tools: [sarif(pattern: "${env.REPORTS_DIR}/semgrep.sarif", id: 'semgrep', name: 'Semgrep Security Scan')]
                    )
                } else {
                    echo "WARNING: Semgrep SARIF report is missing!"
                    currentBuild.result = 'UNSTABLE'
                }

                // Ingest unit tests
                if (fileExists("${env.REPORTS_DIR}/junit.xml")) {
                    echo 'Publishing JUnit test results...'
                    junit testResults: "${env.REPORTS_DIR}/junit.xml", allowEmptyResults: true
                } else {
                    echo "WARNING: JUnit report is missing!"
                    currentBuild.result = 'UNSTABLE'
                }


                // Ingest HTML Coverage
                if (fileExists("${env.REPORTS_DIR}/htmlcov/index.html")) {
                    echo 'Publishing HTML coverage dashboard...'
                    try {
                        publishHTML([
                            allowMissing: true,
                            alwaysLinkToLastBuild: true,
                            keepAll: true,
                            reportDir: "${env.REPORTS_DIR}/htmlcov",
                            reportFiles: 'index.html',
                            reportName: 'HTML Coverage Report'
                        ])
                    } catch (Exception e) {
                        echo "WARNING: HTML Publisher plugin failed or is not available: ${e.message}"
                    }
                } else {
                    echo "WARNING: HTML Coverage report is missing!"
                    currentBuild.result = 'UNSTABLE'
                }

                echo "Build Summary: Job: ${env.JOB_NAME} | Build: #${env.BUILD_NUMBER} | Status: ${currentBuild.currentResult}"
            }
            cleanWs()
        }
        success {
            echo 'SUCCESS: The pipeline completed successfully!'
        }
        failure {
            echo 'FAILURE: The pipeline failed. Please check the logs above for details.'
        }
    }
}
