import test from 'node:test'
import assert from 'node:assert/strict'
import { componentDisplaySubtitle, componentDisplayTitle } from '../src/shared/componentDisplay.js'

test('passive components prefer electrical value over model', () => {
  const resistor = {
    category: { name: '电阻' },
    model: 'FRC0805F1R00TS',
    name: '1Ω ±1% 125mW 厚膜电阻 编带',
    package: '0805',
    lcsc_number: 'C2907233'
  }
  assert.equal(componentDisplayTitle(resistor), '1Ω')
  assert.match(componentDisplaySubtitle(resistor), /FRC0805F1R00TS/)

  const capacitor = {
    category: { name: '电容' },
    model: 'CL10B104KB8NNNC',
    normalized_spec: '100nF ±10% 50V',
    package: '0603'
  }
  assert.equal(componentDisplayTitle(capacitor), '100nF')
})

test('engineering IC module and sensor categories prefer model over parameters', () => {
  const powerIc = {
    category: { name: '电源' },
    model: 'AMS1117-3.3',
    normalized_spec: '3.3V 1A',
    package: 'SOT-223',
    lcsc_number: 'C6186'
  }
  assert.equal(componentDisplayTitle(powerIc), 'AMS1117-3.3')
  assert.match(componentDisplaySubtitle(powerIc), /^3\.3V 1A/)

  const devBoard = {
    category: { name: '开发板' },
    model: 'ESP32-S3-DevKitC-1',
    normalized_spec: '16MB Flash 8MB PSRAM',
    package: 'Type-C'
  }
  assert.equal(componentDisplayTitle(devBoard), 'ESP32-S3-DevKitC-1')
  assert.match(componentDisplaySubtitle(devBoard), /16MB Flash 8MB PSRAM/)

  const sensor = {
    category: { name: '传感器' },
    model: 'INA226',
    normalized_spec: '36V 16bit',
    name: '高侧电流检测传感器'
  }
  assert.equal(componentDisplayTitle(sensor), 'INA226')
  assert.match(componentDisplaySubtitle(sensor), /36V 16bit/)
})

test('semiconductor titles prefer real model names over electrical ratings', () => {
  const diode = {
    category: { name: '二极管' },
    model: '40V 1A',
    name: 'SS14 肖特基二极管',
    normalized_spec: '40V 1A',
    source_title: '电压:40V 电流:1A 编带',
    warehouse_code: 'DIO-00000048'
  }
  assert.equal(componentDisplayTitle(diode), 'SS14')
  assert.match(componentDisplaySubtitle(diode), /^40V 1A/)

  const transistor = {
    category: '三极管',
    name: '0.5A 25V 编带',
    model: '',
    source_title: 'PNP 电流:0.5A 电压:25V 编带',
    warehouse_code: 'BJT-00000050'
  }
  assert.equal(componentDisplayTitle(transistor), 'BJT-00000050')

  const mosfet = {
    category: { name: 'MOS管' },
    model: '',
    name: 'AO3401A P-MOS 30V 4.2A',
    normalized_spec: '30V 4.2A'
  }
  assert.equal(componentDisplayTitle(mosfet), 'AO3401A')
})
