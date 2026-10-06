<script setup lang="ts">
import { websiteSections, type WebsiteDetails } from '../website-details'

defineProps<{ value: WebsiteDetails; passwordScope: string }>()
defineEmits<{ 'open-url': [url: string] }>()
</script>

<template>
  <div class="attachment-section website-detail-section">
    <div class="detail-section-heading"><div><h3>对应办理网址</h3></div></div>
    <div v-for="website in websiteSections" :key="`${passwordScope}-${website.url}`" class="website-detail-card">
      <h4>{{ website.label }}</h4>
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item label="网址"><el-button v-if="value[website.url]" link type="primary" class="website-detail-url" @click="$emit('open-url', value[website.url]!)">{{ value[website.url] }}</el-button><span v-else>—</span></el-descriptions-item>
        <el-descriptions-item label="账号"><span class="website-detail-text">{{ value[website.account] || '—' }}</span></el-descriptions-item>
        <el-descriptions-item label="密码"><el-input v-if="value[website.password]" :model-value="value[website.password] || ''" type="password" show-password readonly autocomplete="off" :aria-label="`${website.label}网站密码`" /><span v-else>—</span></el-descriptions-item>
        <el-descriptions-item label="备注"><span class="website-detail-text">{{ value[website.notes] || '—' }}</span></el-descriptions-item>
      </el-descriptions>
    </div>
  </div>
</template>
