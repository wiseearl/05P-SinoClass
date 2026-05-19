# ApikeyHidding Python 程式建立紀錄

## 目標

建立一支可讀取 ApikeyHidding/config-apikeyhidding.txt 的 Python 程式 apikeyhidding.py，使用 keyfile 指向的 Ollama API key 串接雲端 Ollama，送出 request="Hello"，並可透過 model 參數指定模型，例如 qwen3.5:4b，將回覆寫入 output=./output.txt。

## 建立流程

1. 檢查現有設定檔 ApikeyHidding/config-apikeyhidding.txt，確認內容包含 keyfile、request、output 三個欄位。
2. 參考既有的 OllamaApi/ollama-api.py 設定解析與 HTTP POST 實作，保留相同的 key=value 設定格式。
3. 查核 Ollama 雲端 API 文件，確認雲端 base URL 為 https://ollama.com/api，並以 Authorization: Bearer <API_KEY> 方式帶入驗證。
4. 新增 ApikeyHidding/apikeyhidding.py，實作以下功能：
   - 自動讀取 ApikeyHidding/config-apikeyhidding.txt
   - 依 keyfile 讀取 API key
   - 預設呼叫 https://ollama.com/api/chat
   - 若設定檔未指定 model，先呼叫 /tags 自動選擇第一個非 embedding 模型
   - 將 request 內容包成 chat message 後送出
   - 將回覆寫入設定檔指定的 output 路徑
5. 執行 Python 語法檢查，確認新檔可以正常編譯。
6. 直接執行腳本，確認可以使用現有 keyfile 對雲端 Ollama 發送 Hello 並產生 output.txt。
7. 更新 ApikeyHidding/config-apikeyhidding.txt，加入 model=qwen3.5:4b，讓模型可直接由設定檔指定。
8. 調整 ApikeyHidding/output.txt 的輸出格式，從原本只記錄回答內容，改為同時記錄 question、answer、model。

## 設定檔格式

目前專案設定如下：

```txt
keyfile=key-ollama.txt
request="Hello"
model=qwen3.5:4b
output=./output.txt
```

其他可選擴充欄位：

```txt
base_url="https://ollama.com/api"
endpoint="/chat"
timeout="60"
stream="false"
system="You are a helpful assistant."
```

## 執行方式

在專案根目錄執行：

```powershell
python ApikeyHidding/apikeyhidding.py
```

執行完成後，問題、回覆內容與使用模型都會寫入 ApikeyHidding/output.txt。

## 程式行為

- keyfile 會以設定檔所在目錄為相對基準。
- output 也會以設定檔所在目錄為相對基準。
- 若 config-apikeyhidding.txt 中有 model，程式會直接使用指定模型。
- 若未設定 model，程式會呼叫雲端 Ollama /tags 自動選擇第一個非 embedding 模型。
- 預設使用雲端 Ollama chat API；若需要也可改為 /generate。
- output.txt 會固定輸出 `question: ...`、`answer: ...`、`model: ...` 三行。
- 若 API key 無效、模型不存在或帳號沒有可用模型，程式會回報 HTTP 錯誤內容。

## 驗證

已完成驗證：

- python -m py_compile ApikeyHidding/apikeyhidding.py
- python ApikeyHidding/apikeyhidding.py

實際執行結果：

- 成功讀取 ApikeyHidding/config-apikeyhidding.txt
- 成功讀取 ApikeyHidding/key-ollama.txt
- 成功呼叫 https://ollama.com/api/chat
- 目前可由設定檔直接指定模型 qwen3.5:4b
- 成功取得 Hello 的回覆，並以 question、answer、model 格式寫入 ApikeyHidding/output.txt
