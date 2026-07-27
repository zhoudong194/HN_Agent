Get-ChildItem "D:\Acode\HN_Agent\models\bge-reranker-base" -Recurse -File | ForEach-Object { "$($_.FullName) $($_.Length)" }
