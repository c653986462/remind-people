<script setup lang="ts">
import { Link } from '@element-plus/icons-vue'
import { websiteSections, type WebsiteForm } from '../website-details'

defineProps<{ model: WebsiteForm; passwordScope: string }>()
</script>

<template>
  <div class="form-section span-two"><div><b>对应办理网址</b><span>分别维护办理入口、账号、密码和备注</span></div></div>
  <div v-for="website in websiteSections" :key="website.url" class="website-form-card span-two form-grid">
    <el-form-item :label="`${website.label}网址`" :prop="website.url" class="span-two"><el-input v-model="model[website.url]" :prefix-icon="Link" placeholder="网址或说明（选填）" maxlength="500" /></el-form-item>
    <el-form-item label="账号" :prop="website.account"><el-input v-model="model[website.account]" :name="website.account" autocomplete="off" placeholder="网站登录账号（选填）" maxlength="200" /></el-form-item>
    <el-form-item label="密码" :prop="website.password"><el-input :key="`${passwordScope}-${website.password}`" v-model="model[website.password]" :name="website.password" type="password" show-password autocomplete="new-password" placeholder="网站登录密码（选填）" maxlength="1024" /></el-form-item>
    <el-form-item label="备注" :prop="website.notes" class="span-two"><el-input v-model="model[website.notes]" type="textarea" :rows="2" placeholder="该网址的办理说明或其他备注（选填）" maxlength="5000" /></el-form-item>
  </div>
</template>
