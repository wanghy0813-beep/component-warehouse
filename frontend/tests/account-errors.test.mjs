import test from 'node:test'
import assert from 'node:assert/strict'
import {
  accountErrorMessage,
  createMessageDeduper,
  isAccountServiceUnavailable
} from '../src/shared/accountErrors.js'

test('account errors identify gateway and network outages', () => {
  const gateway = { response: { status: 502, data: '<html>bad gateway</html>' } }
  assert.equal(isAccountServiceUnavailable(gateway), true)
  assert.match(accountErrorMessage(gateway), /HTTP 502/)

  const network = { code: 'ERR_NETWORK', request: {} }
  assert.equal(isAccountServiceUnavailable(network), true)
  assert.match(accountErrorMessage(network), /无法连接统一账号服务/)
})

test('structured account API messages take precedence', () => {
  const error = {
    response: {
      status: 401,
      data: { error: { message: '手机号或密码错误' } }
    }
  }
  assert.equal(accountErrorMessage(error), '手机号或密码错误')
})

test('account message deduper suppresses repeated notifications briefly', () => {
  const shouldNotify = createMessageDeduper(2500)
  assert.equal(shouldNotify('服务不可用', 1000), true)
  assert.equal(shouldNotify('服务不可用', 2000), false)
  assert.equal(shouldNotify('服务不可用', 4000), true)
})
