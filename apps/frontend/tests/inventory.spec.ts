import { test, expect } from '@playwright/test';

test('English UI supports a complete inventory workflow with Chinese data', async ({ page }) => {
  const tag = `UI${Date.now()}`;
  await page.goto('/servers');
  await expect(page.getByRole('heading', {name:'Physical Servers', exact:true})).toBeVisible();
  await page.getByRole('link', {name:'Add Server', exact:true}).first().click();
  await page.getByLabel('Server Name').fill('实验服务器');
  await page.getByLabel('Service Tag').fill(tag);
  await page.getByLabel('Model *', {exact:true}).fill('R750');
  await page.getByLabel('Management IP').fill('192.0.2.5');
  await page.getByLabel('Notes', {exact:true}).fill('中文备注');
  await page.getByRole('button', {name:'Add Server', exact:true}).click();
  await expect(page.getByRole('heading', {name:'实验服务器'})).toBeVisible();
  await expect(page.getByText('中文备注', {exact:true})).toBeVisible();
  const detailUrl = page.url();
  await page.getByRole('link', {name:'Edit Server'}).click();
  await page.getByLabel('Owner', {exact:true}).fill('张三');
  await page.getByLabel('Status', {exact:true}).selectOption('in_use');
  await page.getByRole('button', {name:'Save Changes'}).click();
  await expect(page.getByText('张三', {exact:true})).toBeVisible();
  await page.getByRole('link', {name:'Back to inventory'}).click();
  await page.getByLabel('Search inventory').fill(tag.toLowerCase());
  await page.getByLabel('Model', {exact:true}).fill('R750');
  await page.getByLabel('Status', {exact:true}).selectOption('in_use');
  await page.getByRole('button', {name:'Search', exact:true}).click();
  await expect(page.getByRole('row')).toHaveCount(2);
  const result = page.getByRole('row').filter({hasText:tag});
  await expect(result.getByRole('link', {name:'实验服务器', exact:true})).toBeVisible();
  await expect(page.getByText('In Use', {exact:true}).last()).toBeVisible();
  await result.getByRole('link', {name:'实验服务器', exact:true}).click();
  await page.getByRole('button', {name:'Delete Server', exact:true}).click();
  await expect(page.getByRole('dialog')).toContainText(tag);
  await expect(page.getByRole('button', {name:'Cancel', exact:true})).toBeFocused();
  await page.getByRole('button', {name:'Cancel', exact:true}).click();
  await expect(page.getByRole('heading', {name:'实验服务器'})).toBeVisible();
  await page.getByRole('button', {name:'Delete Server', exact:true}).click();
  await page.getByRole('button', {name:'Delete Permanently'}).click();
  await expect(page.getByRole('heading', {name:'Physical Servers', exact:true})).toBeVisible();
  await page.goto(detailUrl);
  await expect(page.getByRole('alert')).toContainText('Server not found.');
});

test('failed form submission keeps user input and allows retry', async ({ page }) => {
  await page.goto('/servers/new');
  await page.getByLabel('Server Name').fill('保留输入');
  await page.getByLabel('Service Tag').fill('RETRY');
  await page.getByLabel('Model *', {exact:true}).fill('R750');
  await page.route('**/api/servers', route => route.fulfill({status:503, contentType:'application/json', body:JSON.stringify({message:'The service is temporarily unavailable. Please try again.'})}));
  await page.getByRole('button', {name:'Add Server', exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Please try again.');
  await expect(page.getByLabel('Server Name')).toHaveValue('保留输入');
  await expect(page.getByRole('button', {name:'Add Server', exact:true})).toBeEnabled();
});

test('list request failure provides an English retry action', async ({ page }) => {
  await page.route('**/api/servers?*', route => route.abort());
  await page.goto('/servers');
  await expect(page.getByRole('alert')).toContainText('Unable to connect.');
  await page.unroute('**/api/servers?*');
  await page.getByRole('button', {name:'Try Again'}).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
});
