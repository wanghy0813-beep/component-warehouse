import { accountErrorMessage, createMessageDeduper } from './accountErrors'
import { ElMessage } from './elementApi'

const shouldNotify = createMessageDeduper()

export function notifyAccountError(error, fallback) {
  const message = accountErrorMessage(error, fallback)
  if (shouldNotify(message)) ElMessage.error(message)
  return message
}
