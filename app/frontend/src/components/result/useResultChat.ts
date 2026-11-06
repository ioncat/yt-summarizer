import { useEffect, useRef, useState } from 'react'
import { saveChatHistory, clearChatHistory, ResultResponse } from '../../api'
import { Setter, Tab } from './helpers'

interface UseResultChatParams {
  videoId: string | undefined
  result: ResultResponse | null
  chatModel: string
  summaryModel: string
  ollamaUrl: string
  setActiveTab: Setter<Tab>
}

class ChatStreamError extends Error {}

/** The same words as the backend's empty-answer message for the other steps (services/ollama_options.py). */
export function emptyChatAnswerMessage(sawThinking: boolean): string {
  return sawThinking
    ? 'The model returned no answer (thinking used the whole context). Use a model without thinking, or raise the context limit in Settings → General.'
    : 'The model returned nothing.'
}

export function useResultChat({ videoId, result, chatModel, summaryModel, ollamaUrl, setActiveTab }: UseResultChatParams) {
  const [chatHistory, setChatHistory] = useState<Array<{ role: 'user' | 'assistant'; content: string }>>([])
  const [chatInput, setChatInput]     = useState('')
  const [isChatting, setIsChatting]   = useState(false)
  const [chatCopied, setChatCopied]   = useState(false)
  const ollamaMessagesRef    = useRef<Array<{ role: string; content: string }>>([])
  const chatEndRef           = useRef<HTMLDivElement>(null)
  const chatInputRef         = useRef<HTMLTextAreaElement>(null)
  const chatHistoryLoadedRef = useRef(false)

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatHistory])

  async function sendChatMessage() {
    const question = chatInput.trim()
    const activeChatModel = chatModel || summaryModel
    if (!question || isChatting || !ollamaUrl || !activeChatModel || !result) return

    if (ollamaMessagesRef.current.length === 0) {
      const sourceText = result.cleaned_text ?? result.formatted_text ?? ''
      const CHAT_SYSTEM = 'You are a helpful assistant answering questions about a video. ' +
        'The full transcript is provided below. Answer questions based on the transcript content. ' +
        'Respond in the same language as the question.'
      ollamaMessagesRef.current = [
        { role: 'system', content: CHAT_SYSTEM },
        { role: 'user', content: `Video transcript:\n\n${sourceText}` },
        { role: 'assistant', content: result.summary_text
            ? `I have read the transcript. Here is a summary:\n\n${result.summary_text}`
            : 'I have read the transcript.' },
      ]
    }

    ollamaMessagesRef.current = [...ollamaMessagesRef.current, { role: 'user', content: question }]
    setChatHistory(prev => [...prev, { role: 'user', content: question }, { role: 'assistant', content: '' }])
    setChatInput('')
    setIsChatting(true)

    let fullResponse = ''
    let sawThinking = false            // the model "thought" but gave no answer: the context was used up (NS-26)
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: activeChatModel, messages: ollamaMessagesRef.current }),
      })
      if (!response.ok) throw new Error(`Ollama error ${response.status}`)

      const reader  = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer    = ''

      const processLine = (line: string) => {
        if (!line.trim()) return
        try {
          const json  = JSON.parse(line)
          if (json.error) throw new ChatStreamError(String(json.error))        // the backend's {"error": ...} line
          if (json.message?.thinking) sawThinking = true
          const token = json.message?.content ?? json.response ?? ''
          if (token) {
            fullResponse += token
            setChatHistory(prev => {
              const updated = [...prev]
              updated[updated.length - 1] = { role: 'assistant', content: fullResponse }
              return updated
            })
          }
        } catch (e) { if (e instanceof ChatStreamError) throw e /* else: skip a malformed line */ }
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) { if (buffer.trim()) processLine(buffer); break }
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()!
        lines.forEach(processLine)
      }

      if (!fullResponse.trim()) {
        // an empty answer is not an answer: say why instead of leaving an empty bubble, and do not add it to the conversation
        setChatHistory(prev => {
          const updated = [...prev]
          updated[updated.length - 1] = { role: 'assistant', content: `⚠ ${emptyChatAnswerMessage(sawThinking)}` }
          return updated
        })
        return
      }
      ollamaMessagesRef.current = [...ollamaMessagesRef.current, { role: 'assistant', content: fullResponse }]
      if (fullResponse && videoId) {
        const savedHistory = [
          ...chatHistory,
          { role: 'user' as const, content: question },
          { role: 'assistant' as const, content: fullResponse },
        ]
        saveChatHistory(videoId, savedHistory).catch(() => {})
        setActiveTab('chat')
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setChatHistory(prev => {
        const updated = [...prev]
        updated[updated.length - 1] = { role: 'assistant', content: `⚠ ${msg}` }
        return updated
      })
    } finally {
      setIsChatting(false)
      chatInputRef.current?.focus()
    }
  }

  async function deleteChatMessage(index: number) {
    const updated = chatHistory.filter((_, i) => i !== index)
    setChatHistory(updated)
    if (videoId) saveChatHistory(videoId, updated).catch(() => {})
  }

  async function handleClearChat() {
    if (!window.confirm('Clear entire chat history? This cannot be undone.')) return
    setChatHistory([])
    ollamaMessagesRef.current = []
    if (videoId) clearChatHistory(videoId).catch(() => {})
  }

  function copyChat() {
    if (!result || chatHistory.length === 0) return
    const lines = [
      `Video: ${result.title ?? ''}`,
      `\nSummary:\n${result.summary_text ?? ''}`,
      ...chatHistory.map(m => `\n${m.role === 'user' ? 'Q' : 'A'}: ${m.content}`),
    ].join('\n')
    navigator.clipboard.writeText(lines).then(() => { setChatCopied(true); setTimeout(() => setChatCopied(false), 2000) })
  }

  return {
    chatHistory, setChatHistory, chatInput, setChatInput, isChatting, chatCopied,
    chatEndRef, chatInputRef, chatHistoryLoadedRef,
    sendChatMessage, deleteChatMessage, handleClearChat, copyChat,
  }
}
