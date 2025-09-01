# nono-wallet (MVP)

## Auth
ضع الهيدر في كل الطلبات:
`X-Api-Key: <YOUR_API_TOKEN>`

## Endpoints
- `GET /health` → `{ ok: true }`
- `POST /wallet/create` → `{ ok, wallet_id, balance }`
- `GET /wallet/balance?wallet_id=...`
- `POST /wallet/deposit { wallet_id, amount }`
- `POST /wallet/withdraw { wallet_id, amount }`
- `POST /wallet/transfer { from_wallet_id, to_wallet_id, amount }`
- `GET /transactions?wallet_id=...&type=&from=&to=&limit=&offset=`
- `GET /transactions/export.csv?wallet_id=...&type=&from=&to=`

## Examples (PowerShell)
```powershell
$H = @{ "X-Api-Key" = "<YOUR_API_TOKEN>" }
$w = (irm "<BASE>/wallet/create" -Method POST -Headers $H).wallet_id
$body = @{ wallet_id = $w; amount = 200 } | ConvertTo-Json
irm "<BASE>/wallet/deposit" -Method POST -Headers $H -Body $body -ContentType "application/json"
irm "<BASE>/transactions?wallet_id=$w" -Headers $H | ConvertTo-Json -Depth 6
iwr "<BASE>/transactions/export.csv?wallet_id=$w" -Headers $H -OutFile "transactions_$w.csv"
