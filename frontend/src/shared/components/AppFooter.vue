<template>
  <footer class="app-footer" aria-label="版权信息">
    <span>{{ COPYRIGHT_TEXT }}</span>
    <a
      v-if="ICP_RECORD_TEXT"
      :href="ICP_RECORD_URL"
      target="_blank"
      rel="noopener noreferrer"
    >{{ ICP_RECORD_TEXT }}</a>
    <a
      v-if="PUBLIC_SECURITY_RECORD_TEXT"
      :href="PUBLIC_SECURITY_RECORD_URL"
      target="_blank"
      rel="noopener noreferrer"
    >{{ PUBLIC_SECURITY_RECORD_TEXT }}</a>
  </footer>
</template>

<script setup>
import {
  COPYRIGHT_TEXT,
  ICP_RECORD_TEXT,
  ICP_RECORD_URL,
  PUBLIC_SECURITY_RECORD_TEXT,
  PUBLIC_SECURITY_RECORD_URL
} from '../branding'
</script>

<style scoped>
.app-footer {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px 14px;
  padding: 20px 12px 8px;
  color: #8a99aa;
  font-size: 12px;
  line-height: 1.7;
  text-align: center;
}

.app-footer a {
  color: inherit;
  text-decoration: none;
}

.app-footer a:hover {
  color: #475467;
}
</style>
