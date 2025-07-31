
const BASE_API_URL = 'https://7vyy10lcgd.execute-api.us-east-1.amazonaws.com/api';

fetch(`${BASE_API_URL}/data`)
  .then(async (response) => {
    const contentType = response.headers.get("content-type");
    if (!response.ok) {
      throw new Error(`HTTP error: ${response.status}`);
    }
    if (!contentType || !contentType.includes("application/json")) {
      const text = await response.text();
      throw new Error("Expected JSON but got HTML:\n" + text.substring(0, 300));
    }
    return response.json();
  })
  .then(data => {
    console.log("Rendering records...", data);
    const tbody = document.querySelector('#recordsTable tbody');
    if (!tbody) {
      console.error("Could not find #recordsTable tbody");
      return;
    }

    tbody.innerHTML = data.map(record => \`
      <tr>
        <td>\${record.member_id}</td>
        <td>\${record.name} \${record.last_name}</td>
        <td>\${record.email || ''}</td>
        <td>\${record.membership_expires || ''}</td>
        <td>\${record.active_flag ? 'Active' : 'Inactive'}</td>
      </tr>
    \`).join('');
  })
  .catch(error => {
    console.error("Data load failed:", error);
    const tbody = document.querySelector('#recordsTable tbody');
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="5">Error loading data</td></tr>`;
    }
  });
