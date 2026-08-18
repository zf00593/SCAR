param(
    [Parameter(Mandatory=$true)]
    [string]$message
)

git add .

git commit -m "$message"

git push
